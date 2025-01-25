import logging
import datetime
from fastapi import Request, HTTPException
from app.database import db
from app.database.models import Message
from app.database.enums import MessageRole, UserState
from app.utils.string_manager import strings, StringCategory
from app.services.whatsapp_service import whatsapp_client
from fastapi.responses import JSONResponse
from app.utils.whatsapp_utils import get_request_type, RequestType

logger = logging.getLogger(__name__)

DAILY_MESSAGES_LIMIT = 2
APP_DAILY_MESSAGES_LIMIT = 10000
DAILY_TOKEN_LIMIT = 50000
APP_DAILY_TOKEN_LIMIT = 1000000

user_usage = {}
app_usage = {
    "messages": 0,
    "tokens": 0,
    "reset_time": datetime.datetime.now() + datetime.timedelta(days=1),
}


def reset_limits():
    now = datetime.datetime.now()
    logger.debug(f"Checking if limits should be reset. Current time: {now}")
    if app_usage["reset_time"] < now:
        logger.info("Resetting all usage limits.")
        user_usage.clear()
        app_usage["messages"] = 0
        app_usage["tokens"] = 0
        app_usage["reset_time"] = now + datetime.timedelta(days=1)
        logger.debug(f"New reset_time: {app_usage['reset_time']}")
    else:
        logger.debug("Limits do not need to be reset.")


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


async def respond_with_rate_limit_message(
    phone_number: str, message_key: str
) -> JSONResponse:
    logger.debug(f"Responding with rate-limit message. message_key={message_key}")
    user = await db.get_or_create_user(wa_id=phone_number)
    user.state = UserState.rate_limited
    user = await db.update_user(user)
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


async def rate_limit(request: Request):
    logger.debug("Entering rate_limit function.")
    reset_limits()
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

    if phone_number not in user_usage:
        logger.debug(f"Setting initial usage for new phone number: {phone_number}")
        user_usage[phone_number] = {"messages": 0, "tokens": 0}

    if app_usage["messages"] >= APP_DAILY_MESSAGES_LIMIT:
        return await respond_with_rate_limit_message(
            phone_number, "global_message_limit"
        )
    if app_usage["tokens"] + tokens_used > APP_DAILY_TOKEN_LIMIT:
        return await respond_with_rate_limit_message(phone_number, "global_token_limit")
    if user_usage[phone_number]["messages"] >= DAILY_MESSAGES_LIMIT:
        return await respond_with_rate_limit_message(phone_number, "user_message_limit")
    if user_usage[phone_number]["tokens"] + tokens_used > DAILY_TOKEN_LIMIT:
        return await respond_with_rate_limit_message(phone_number, "user_token_limit")

    logger.info(
        f"Usage incremented for {phone_number}. "
        f"Messages: {user_usage[phone_number]['messages'] + 1}, "
        f"Tokens: {user_usage[phone_number]['tokens'] + tokens_used}"
    )
    user_usage[phone_number]["messages"] += 1
    user_usage[phone_number]["tokens"] += tokens_used
    app_usage["messages"] += 1
    app_usage["tokens"] += tokens_used
