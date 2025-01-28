import logging
from fastapi import Request, HTTPException
from app.utils.whatsapp_utils import get_request_type, RequestType
from app.redis.engine import get_redis_client
from app.config import settings
from app.utils.rate_limit_utils import (
    respond_with_rate_limit_message,
    extract_phone_number,
    get_int_from_redis,
)

logger = logging.getLogger(__name__)

USER_DAILY_MESSAGES_LIMIT = settings.user_daily_messages_limit
GLOBAL_DAILY_MESSAGES_LIMIT = settings.global_daily_messages_limit
USER_DAILY_TOKEN_LIMIT = settings.user_daily_token_limit
GLOBAL_DAILY_TOKEN_LIMIT = settings.global_daily_token_limit


async def rate_limit(request: Request):
    logger.debug("Entering rate_limit function.")
    body = await request.json()
    request_type = get_request_type(body)

    if request_type != RequestType.VALID_MESSAGE:
        logger.debug("Request type is not VALID_MESSAGE. Skipping rate limiting.")
        return

    logger.debug(f"Determined request type in rate Limit: {request_type}")
    phone_number = extract_phone_number(body)
    logger.debug(f"Extracted phone_number: {phone_number}")
    if not phone_number:
        logger.warning("Phone number not found in request body.")
        raise HTTPException(status_code=400, detail="Phone number is required")

    redis_client = get_redis_client()

    user_messages_key = f"daily_limit:user:messages:{phone_number}"
    global_messages_key = "daily_limit:global:messages"
    user_tokens_key = f"daily_limit:user:tokens:{phone_number}"
    global_tokens_key = "daily_limit:global:tokens"

    user_messages = await get_int_from_redis(redis_client, user_messages_key)
    user_messages = await redis_client.incr(user_messages_key)
    global_messages = await redis_client.incr(global_messages_key)

    if user_messages > USER_DAILY_MESSAGES_LIMIT:
        return await respond_with_rate_limit_message(phone_number, "user_message_limit")

    if global_messages > GLOBAL_DAILY_MESSAGES_LIMIT:
        return await respond_with_rate_limit_message(
            phone_number, "global_message_limit"
        )

    user_tokens = await get_int_from_redis(redis_client, user_tokens_key)
    global_tokens = await get_int_from_redis(redis_client, global_tokens_key)

    if user_tokens > USER_DAILY_TOKEN_LIMIT:
        return await respond_with_rate_limit_message(phone_number, "user_token_limit")

    if global_tokens > GLOBAL_DAILY_TOKEN_LIMIT:
        return await respond_with_rate_limit_message(phone_number, "global_token_limit")
    logger.debug(
        f"Usage for user : {phone_number}. "
        f"Messages: {user_messages}, "
        f"Messages limit: {USER_DAILY_MESSAGES_LIMIT}, "
        f"Tokens: {user_tokens}, "
        f"Tokens limit: {USER_DAILY_TOKEN_LIMIT}"
    )
    logger.debug(
        f"Usage for global: "
        f"Global messages: {global_messages}, "
        f"Global messages limit: {GLOBAL_DAILY_MESSAGES_LIMIT}, "
        f"Global tokens: {global_tokens}, "
        f"Global tokens limit: {GLOBAL_DAILY_TOKEN_LIMIT}"
    )
