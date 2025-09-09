import logging
from app.redis.engine import get_redis_client, is_redis_available
from app.redis.redis_keys import RedisKeys
from app.config import settings, Environment
from app.database import db, enums
from app.database.models import User

logger = logging.getLogger(__name__)


class RateLimitService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def check_and_reset_rate_limit_state(self, user: User) -> User:
        """
        Check if user is rate_limited and reset to active if TTL has expired.
        If Redis is not available, reset all rate_limited users to active.
        """
        if user.state != enums.UserState.rate_limited:
            return user

        # If Redis is not available, reset user to active (no rate limiting)
        if not is_redis_available():
            self.logger.info(
                f"Redis unavailable - resetting rate_limited user {user.wa_id} to active state"
            )
            user.state = enums.UserState.active
            await db.update_user(user)
            return user

        try:
            redis = get_redis_client()
            if redis is None:
                # Redis client unavailable, reset to active
                self.logger.info(
                    f"Redis client unavailable - resetting rate_limited user {user.wa_id} to active state"
                )
                user.state = enums.UserState.active
                await db.update_user(user)
                return user

            user_key = RedisKeys.USER_RATE(user.wa_id)
            ttl = await redis.ttl(user_key)

            # If TTL is -2 (key doesn't exist) or -1 (key has no expiry), reset to active
            if ttl <= 0:
                self.logger.info(
                    f"Rate limit expired for user {user.wa_id}, resetting to active state"
                )
                user.state = enums.UserState.active
                await db.update_user(user)
                return user

        except Exception as e:
            self.logger.error(
                f"Error checking rate limit TTL for user {user.wa_id}: {str(e)}"
            )
            # If we can't check Redis, assume the user should remain rate_limited for safety

        return user

    async def check_rate_limit_and_update_state(
        self, user: User, phone_number: str
    ) -> tuple[bool, User]:
        """
        Check if user should be rate limited and update their state accordingly.
        Returns (is_rate_limited, updated_user)
        If Redis is not available, skip rate limiting entirely.
        """
        # Skip rate limiting in development
        if settings.environment not in (Environment.PRODUCTION, Environment.STAGING):
            return False, user

        # Skip rate limiting if Redis is not available
        if not is_redis_available():
            self.logger.debug("Redis unavailable - skipping rate limiting")
            return False, user

        # Validate settings
        if not all(
            [
                settings.time_to_live,
                settings.user_message_limit,
                settings.global_message_limit,
            ]
        ):
            self.logger.error("Missing rate limit settings")
            return False, user

        try:
            redis = get_redis_client()
            if redis is None:
                self.logger.debug("Redis client unavailable - skipping rate limiting")
                return False, user

            # Check user limit
            user_key = RedisKeys.USER_RATE(phone_number)
            assert settings.user_message_limit is not None
            is_exceeded, result = await self._check_rate_limit(
                user_key, settings.user_message_limit
            )

            if is_exceeded:
                self.logger.warning(
                    f"Rate limit exceeded for user {phone_number}: {result}"
                )
                if user.state != enums.UserState.rate_limited:
                    user.state = enums.UserState.rate_limited
                    await db.update_user(user)
                    self.logger.info(
                        f"Updated user {phone_number} state to rate_limited"
                    )
                return True, user

            user_count = result

            # Check global limit
            global_key = RedisKeys.GLOBAL_RATE
            assert settings.global_message_limit is not None
            is_exceeded, result = await self._check_rate_limit(
                global_key, settings.global_message_limit
            )

            if is_exceeded:
                self.logger.warning(f"Global rate limit exceeded: {result}")
                if user.state != enums.UserState.rate_limited:
                    user.state = enums.UserState.rate_limited
                    await db.update_user(user)
                    self.logger.info(
                        f"Updated user {phone_number} state to rate_limited (global limit)"
                    )
                return True, user

            global_count = result

            self.logger.debug(
                f"Rate limits: {user_count}/{settings.user_message_limit}, "
                f"Global: {global_count}/{settings.global_message_limit}"
            )

            return False, user

        except Exception as e:
            self.logger.error(f"Redis error in rate limiter: {str(e)}")
            # Don't block requests if Redis fails
            return False, user

    async def _check_rate_limit(self, key: str, limit: int) -> tuple[bool, int]:
        """
        Check if rate limit is exceeded for given key and return (is_exceeded, current_count).
        If Redis is not available, always return (False, 0).
        """
        if not is_redis_available():
            return False, 0

        redis = get_redis_client()
        if redis is None:
            return False, 0

        assert settings.time_to_live
        pipe = await redis.pipeline()
        await pipe.incr(key)
        await pipe.expire(key, settings.time_to_live)
        result = await pipe.execute()
        count = int(result[0])

        if count > limit:
            self.logger.warning(
                f"Rate limit exceeded for {key}: {count}. The limit was {limit}"
            )
            ttl = await redis.ttl(key)
            return True, ttl
        return False, count


# Global instance
rate_limit_service = RateLimitService()
