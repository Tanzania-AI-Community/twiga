import logging
from fastapi import Request, HTTPException
from app.database import db
from app.database.models import Message
from app.database.enums import MessageRole
from app.utils.string_manager import strings, StringCategory
from app.services.whatsapp_service import whatsapp_client
from fastapi.responses import JSONResponse
from app.utils.whatsapp_utils import get_request_type, RequestType
from app.redis.engine import get_redis_client

logger = logging.getLogger(__name__)

DAILY_MESSAGES_LIMIT = 2
APP_DAILY_MESSAGES_LIMIT = 10000
DAILY_TOKEN_LIMIT = 50000
APP_DAILY_TOKEN_LIMIT = int(1000000)


async def respond_with_rate_limit_message(
    phone_number: str, message_key: str
) -> JSONResponse:
    logger.debug(f"Responding with rate-limit message. message_key={message_key}")
    user = await db.get_or_create_user(wa_id=phone_number)
    assert user.id is not None

    response_text = strings.get_string(StringCategory.RATE_LIMIT, message_key)
    await whatsapp_client.send_message(user.wa_id, response_text)
    await db.create_new_message(
        Message(
            user_id=user.id,
            role=MessageRole.assistant,
            content=response_text,
        )
    )
    return JSONResponse(content={"status": "ok"}, status_code=200)


def extract_phone_number(body: dict) -> str | None:
    logger.debug("Attempting to extract phone_number from the request body.")
    try:
        return body["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
    except KeyError:
        logger.debug("Failed to find wa_id in contacts. Trying 'messages' field.")
        try:
            return body["entry"][0]["changes"][0]["value"]["messages"][0]["from"]
        except KeyError:
            logger.warning("Could not extract phone_number from request body.")
            return None


async def get_int_from_redis(redis_client, key: str) -> int:
    value = await redis_client.get(key)
    return int(value) if value else 0


async def rate_limit(request: Request):
    logger.debug("Entering rate_limit function.")
    body = await request.json()
    request_type = get_request_type(body)

    if request_type != RequestType.VALID_MESSAGE:
        logger.debug("Request type is not VALID_MESSAGE. Skipping rate limiting.")
        return

    logger.debug(f"Determined request type in rate Limit: {request_type}")
    phone_number = extract_phone_number(body)
    tokens_used = body.get("tokens_used", 0)
    logger.debug(f"Extracted phone_number: {phone_number}")
    if not phone_number:
        logger.warning("Phone number not found in request body.")
        raise HTTPException(status_code=400, detail="Phone number is required")

    redis_client = get_redis_client()

    user_key = f"rate_limit:user:{phone_number}"
    app_key = "rate_limit:app"

    user_messages = await get_int_from_redis(redis_client, f"{user_key}:messages")
    user_messages = await redis_client.incr(f"{user_key}:messages")
    await redis_client.expire(f"{user_key}:messages", 86400)

    if user_messages > DAILY_MESSAGES_LIMIT:
        return await respond_with_rate_limit_message(phone_number, "user_message_limit")

    app_messages = await get_int_from_redis(redis_client, f"{app_key}:messages")
    app_messages = await redis_client.incr(f"{app_key}:messages")
    await redis_client.expire(f"{app_key}:messages", 86400)

    if app_messages > APP_DAILY_MESSAGES_LIMIT:
        return await respond_with_rate_limit_message(
            phone_number, "global_message_limit"
        )

    user_tokens = await get_int_from_redis(redis_client, f"{user_key}:tokens")
    user_tokens = await redis_client.incrby(f"{user_key}:tokens", tokens_used)
    await redis_client.expire(f"{user_key}:tokens", 86400)

    if user_tokens > DAILY_TOKEN_LIMIT:
        return await respond_with_rate_limit_message(phone_number, "user_token_limit")

    app_tokens = await get_int_from_redis(redis_client, f"{app_key}:tokens")
    app_tokens = await redis_client.incrby(f"{app_key}:tokens", tokens_used)
    await redis_client.expire(f"{app_key}:tokens", 86400)

    if app_tokens > APP_DAILY_TOKEN_LIMIT:
        return await respond_with_rate_limit_message(phone_number, "global_token_limit")
    logger.info(
        f"Usage incremented for {phone_number}. "
        f"Messages: {user_messages}, "
        f"Tokens: {user_tokens}"
    )
