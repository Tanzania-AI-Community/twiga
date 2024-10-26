import json
import logging
from typing import Optional
from fastapi import Request
from fastapi.responses import JSONResponse

from app.database.models import User, UserState
from app.utils.whatsapp_utils import (
    extract_message_body,
    extract_message_info,
    generate_payload,
    get_text_payload,
    is_message_recent,
    is_status_update,
    is_valid_whatsapp_message,
)

from db.utils import AppDatabase
from app.services.whatsapp_service import whatsapp_client
from app.services.llm_service import llm_client
from app.services.state_service import state_client
from app.services.onboarding_service import onboarding_client
from app.database.db import get_or_create_user

logger = logging.getLogger(__name__)


async def handle_request(request: Request) -> JSONResponse:
    """
    Handles HTTP requests to this webhook for message, sent, delivered, and read events.
    Includes user management with database integration.
    """
    try:
        body = await request.json()

        # Check if it's a WhatsApp status update (sent, delivered, read)
        if is_status_update(body):
            return whatsapp_client.handle_status_update(body)

        # Process non-status updates (message, other)
        if not is_valid_whatsapp_message(body):
            return JSONResponse(
                content={"status": "error", "message": "Not a WhatsApp API event"},
                status_code=404,
            )

        # Extract message info (NOTE: the message format might look different in flow responses)
        message_info = extract_message_info(body)

        # Get or create user
        user = await get_or_create_user(
            wa_id=message_info["wa_id"], name=message_info["name"]
        )

        # Handle state using the State Service
        response_text, options = state_client.process_state(user)

        if response_text:
            payload = generate_payload(user.wa_id, response_text, options)
            await whatsapp_client.send_message(payload)
            return JSONResponse(
                content={"status": "ok"},
                status_code=200,
            )

        # response_text, options = onboarding_client.process_state(
        #     user, message_info["message"]
        # )
        # if response_text:
        # return JSONResponse(
        #     content=generate_payload(user.wa_id, response_text, options),
        #     status_code=200,
        # )

        # TODO: should also consider the case where the user is onboarding and not active
        if (
            is_message_recent(message_info["timestamp"])
            and user.state == UserState.active
        ):
            # Add check if rate limit is reached here and update the database. Will need some function that brings it back the next day though.
            # if db.is_rate_limit_reached(wa_id):
            #     return await _handle_rate_limit(wa_id, message)

            generated_response = await _process_message(
                user=user,
                message=message_info["message"],
                timestamp=message_info["timestamp"],
            )
            payload = generate_payload(user.wa_id, generated_response)
            await whatsapp_client.send_message(generated_response)
            return JSONResponse(content={"status": "ok"}, status_code=200)
        else:
            logger.warning("Received a message with an outdated timestamp. Ignoring.")
            return JSONResponse(content={"status": "ok"}, status_code=200)

    except json.JSONDecodeError:
        logger.error("Failed to decode JSON")
        return JSONResponse(
            content={"status": "error", "message": "Invalid JSON provided"},
            status_code=400,
        )
    except Exception as e:
        logger.error(f"Unexpected error in webhook handler: {str(e)}")
        return JSONResponse(
            content={"status": "error", "message": "Internal server error"},
            status_code=500,
        )


async def _process_message(user: User, message: dict, timestamp: int) -> Optional[str]:
    """
    Process an incoming WhatsApp message and generate a response.

    Args:
        wa_id (str): WhatsApp ID of the user (phone number).
        name (str): Name of the user.
        message (dict): Message content received from WhatsApp.
        timestamp (int): Timestamp of the message.

    Returns:
        Optional[str]: JSON payload to send back to WhatsApp, or None if no response is required.
    """

    try:
        message_body = extract_message_body(message)
    except ValueError as e:
        logger.error(str(e))
        return None

    # db.store_message(wa_id, message_body, role="user")

    # NOTE: this is a temporary integration for testing purposes
    data = await _handle_llm(user, message_body)
    # if state.get("state") != "completed":
    #     data = _handle_onboarding_flow(wa_id, message_body)
    # else:
    #     data = await _handle_twiga_integration(wa_id, name, message_body)

    return data


def _handle_testing(wa_id: str, message_body: str) -> Optional[str]:
    return get_text_payload(wa_id, message_body.upper())


async def _handle_llm(user: User, message_body: str) -> Optional[str]:

    db = AppDatabase()

    response_text = await llm_client.generate_response(
        user=user, message_body=message_body, verbose=True
    )
    if response_text is None:
        logger.error("For some reason we didn't get a response")
        return None

    # TODO: Store the chatbot response in the database
    # db.store_message(user.wa_id, response_text, role="assistant")
    return get_text_payload(user.wa_id, response_text)


def _handle_onboarding_flow(wa_id: str, message_body: str) -> str:
    response_text, options = onboarding_client.process_state(wa_id, message_body)
    return generate_payload(wa_id, response_text, options)


# TODO: This will be partially deprecated and handled by the state service
async def _handle_rate_limit(wa_id: str, message: dict) -> JSONResponse:
    db = AppDatabase()
    # TODO: This is a good place to use a template instead of hardcoding the message
    logger.warning("Rate limit reached for wa_id: %s", wa_id)
    sleepy_text = (
        "🚫 You have reached your daily messaging limit, so Twiga 🦒 is quite sleepy 🥱 "
        "from all of today's texting. Let's talk more tomorrow!"
    )
    data = get_text_payload(wa_id, sleepy_text)
    db.store_message(wa_id, message, role="user")
    await whatsapp_client.send_message(data)
    return JSONResponse(content={"status": "ok"}, status_code=200)
