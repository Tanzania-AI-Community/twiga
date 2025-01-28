import logging
from fastapi.responses import JSONResponse
from app.database import db
import redis.asyncio as redis
from app.services.whatsapp_service import whatsapp_client
from app.utils.string_manager import strings, StringCategory

logger = logging.getLogger(__name__)


async def respond_with_rate_limit_message(
    phone_number: str, message_key: str
) -> JSONResponse:
    logger.debug(f"Responding with rate-limit message. message_key={message_key}")
    user = await db.get_or_create_user(wa_id=phone_number)
    assert user.id is not None
    response_text = strings.get_string(StringCategory.RATE_LIMIT, message_key)
    await whatsapp_client.send_message(user.wa_id, response_text)
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


async def get_int_from_redis(redis_client: redis.Redis, key: str) -> int:
    value = await redis_client.get(key)
    return int(value) if value else 0
