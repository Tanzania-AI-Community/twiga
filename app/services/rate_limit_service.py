import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from app.utils.whatsapp_utils import extract_message_info, get_request_type, RequestType
from app.redis.engine import get_redis_client
from app.config import Environment, settings
from app.database import db
from app.utils.string_manager import strings, StringCategory
from app.services.whatsapp_service import whatsapp_client
from app.redis.redis_keys import RedisKeys

logger = logging.getLogger(__name__)


class RateLimitResponse(Exception):
    """Custom exception that includes successful response to WhatsApp"""

    def __init__(self):
        self.response = JSONResponse(content={"status": "ok"}, status_code=200)


async def send_rate_limit_message(phone_number: str, message_key: str):
    """Send rate limit message to user."""
    user = await db.get_user_by_waid(wa_id=phone_number)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Use template formatting for time remaining
    response_text = strings.get_string(StringCategory.RATE_LIMIT, message_key)

    await whatsapp_client.send_message(user.wa_id, response_text)


async def check_rate_limit(key: str, limit: int) -> tuple[bool, int]:
    """Check if rate limit is exceeded for given key and return (is_exceeded, current_count)."""
    assert settings.time_to_live
    redis = get_redis_client()
    pipe = await redis.pipeline()
    await pipe.incr(key)
    await pipe.expire(key, settings.time_to_live)
    result = await pipe.execute()
    count = int(result[0])

    if count > limit:
        logger.warning(f"Rate limit exceeded for {key}: {count}. The limit was {limit}")
        ttl = await redis.ttl(key)
        return True, ttl
    return False, count


async def rate_limit(request: Request) -> JSONResponse | None:
    """
    FastAPI dependency for rate limiting WhatsApp messages using rolling 24-hour windows.
    Returns 200 status code even when rate limited to prevent WhatsApp retries.
    """
    # Skip in development
    if settings.environment not in (Environment.PRODUCTION, Environment.STAGING):
        return

    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse request body: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid request body")

    # Only rate limit valid messages
    if get_request_type(body) != RequestType.VALID_MESSAGE:
        return None

    # Validate settings
    if not all(
        [
            settings.time_to_live,
            settings.user_message_limit,
            settings.global_message_limit,
        ]
    ):
        raise ValueError("Missing rate limit settings")

    # Get phone number
    phone_number = extract_message_info(body).get("wa_id")
    if not phone_number:
        raise HTTPException(status_code=400, detail="Phone number is required")

    assert settings.user_message_limit and settings.global_message_limit

    try:
        # Check user limit
        user_key = RedisKeys.USER_RATE(phone_number)
        is_exceeded, result = await check_rate_limit(
            user_key, settings.user_message_limit
        )
        if is_exceeded:
            logger.warning(f"Rate limit exceeded: {result}")
            await send_rate_limit_message(phone_number, "user_message_limit")
            raise RateLimitResponse()

        user_count = result

        # Check global limit
        global_key = RedisKeys.GLOBAL_RATE
        is_exceeded, result = await check_rate_limit(
            global_key, settings.global_message_limit
        )
        if is_exceeded:
            logger.warning(f"Global rate limit exceeded: {result}")
            await send_rate_limit_message(phone_number, "global_message_limit")
            raise RateLimitResponse()

        global_count = result

        logger.debug(
            f"Rate limits: {user_count}/{settings.user_message_limit}, "
            f"Global: {global_count}/{settings.global_message_limit}"
        )

    except RateLimitResponse as e:
        return e.response
    except Exception as e:
        logger.error(f"Redis error in rate limiter: {str(e)}")
        # Don't block requests if Redis fails
        return
