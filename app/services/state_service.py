import logging

from fastapi.responses import JSONResponse

from app.database.models import Message, User
from app.services.onboarding_service import onboarding_client
from app.database import db
from app.services.whatsapp_service import whatsapp_client
from app.database.enums import MessageRole
from app.utils.string_manager import strings, StringCategory
from app.utils.whatsapp_utils import (
    ValidMessageType,
    get_valid_message_type,
)
from app.services.messaging_service import messaging_client
from app.redis.engine import get_redis_client, is_redis_available
from app.redis.redis_keys import RedisKeys
from app.config import settings, Environment
from app.database import enums


class StateHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def handle_blocked(self, user: User) -> JSONResponse:
        assert user.id is not None

        # Check if we've already sent a blocked message to this user
        recent_messages = await db.get_user_message_history(user.id, limit=10)
        if recent_messages:
            # Check if the last assistant message was a blocked message
            assistant_messages = [
                msg for msg in recent_messages if msg.role == MessageRole.assistant
            ]
            if assistant_messages:
                last_assistant_message = assistant_messages[-1]
                blocked_text = strings.get_string(StringCategory.ERROR, "blocked")

                # If the last assistant message was a blocked message, don't send another
                if last_assistant_message.content == blocked_text:
                    self.logger.info(
                        f"Blocked message already sent to user {user.wa_id}, not sending again"
                    )
                    return JSONResponse(
                        content={"status": "ok"},
                        status_code=200,
                    )

        # Send blocked message (first time)
        response_text = strings.get_string(StringCategory.ERROR, "blocked")
        await whatsapp_client.send_message(user.wa_id, response_text)
        await db.create_new_message(
            Message(
                user_id=user.id,
                role=MessageRole.assistant,
                content=response_text,
            )
        )
        self.logger.info(f"Sent blocked message to user {user.wa_id}")
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def handle_rate_limited(self, user: User) -> JSONResponse:
        assert user.id is not None

        # Check if we've already sent a rate limit message to this user
        recent_messages = await db.get_user_message_history(user.id, limit=10)
        if recent_messages:
            # Check if the last assistant message was a rate limit message
            assistant_messages = [
                msg for msg in recent_messages if msg.role == MessageRole.assistant
            ]
            if assistant_messages:
                last_assistant_message = assistant_messages[-1]
                rate_limit_text = strings.get_string(
                    StringCategory.ERROR, "rate_limited"
                )

                # If the last assistant message was a rate limit message, don't send another
                if last_assistant_message.content == rate_limit_text:
                    self.logger.info(
                        f"Rate limit message already sent to user {user.wa_id}, not sending again"
                    )
                    return JSONResponse(
                        content={"status": "ok"},
                        status_code=200,
                    )

        # Send rate limit message (first time)
        response_text = strings.get_string(StringCategory.ERROR, "rate_limited")
        await whatsapp_client.send_message(user.wa_id, response_text)
        await db.create_new_message(
            Message(
                user_id=user.id,
                role=MessageRole.assistant,
                content=response_text,
            )
        )
        self.logger.info(f"Sent rate limit message to user {user.wa_id}")
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def check_and_reset_rate_limit_state(self, user: User) -> User:
        """
        Check if user is rate_limited and reset to active if TTL has expired.
        Check Redis TTL to reset users from rate_limited back to active state.
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

    async def handle_onboarding(self, user: User) -> JSONResponse:
        await onboarding_client.process_state(user)
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def handle_active(
        self, user: User, message_info: dict, user_message: Message
    ) -> JSONResponse:
        message_type = get_valid_message_type(message_info)
        match message_type:
            case ValidMessageType.SETTINGS_FLOW_SELECTION:
                return await messaging_client.handle_settings_selection(
                    user, user_message
                )
            case ValidMessageType.COMMAND:
                return await messaging_client.handle_command_message(user, user_message)
            case ValidMessageType.CHAT:
                return await messaging_client.handle_chat_message(user, user_message)
            case ValidMessageType.OTHER:
                return await messaging_client.handle_other_message(user, user_message)


state_client = StateHandler()
