import json
import logging
from typing import List, Optional
from fastapi import Request
from fastapi.responses import JSONResponse

from app.database.models import Message, MessageRole, User, UserState
from app.utils.whatsapp_utils import (
    extract_message_body,
    extract_message_info,
    generate_payload,
    get_text_payload,
    is_message_recent,
    is_status_update,
    is_valid_whatsapp_message,
)

from app.services.whatsapp_service import whatsapp_client
from app.services.llm_service import llm_client
from app.services.state_service import state_client
from app.services.onboarding_service import onboarding_client
import app.database.db as db

logger = logging.getLogger(__name__)


# TODO: make this function less complex
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

        # Check if message is recent
        if not is_message_recent(message_info["timestamp"]):
            logger.warning("Received a message with an outdated timestamp. Ignoring.")
            return JSONResponse(
                content={"status": "error", "message": "Message is outdated"},
                status_code=400,
            )

        # Get or create user
        user = await db.get_or_create_user(
            wa_id=message_info["wa_id"], name=message_info["name"]
        )

        request_message = extract_message_body(message_info["message"])

        # Upload the message to the database
        user_message = await db.create_new_message(
            Message(user_id=user.id, role=MessageRole.user, content=request_message)
        )

        # Handle state using the State Service
        response_text, options = state_client.process_state(user)

        if response_text is not None:
            # In this scenario the user is in a state that had a predefined response
            payload = generate_payload(user.wa_id, response_text, options)
            await whatsapp_client.send_message(payload)

            # Store the bot response in the database
            await db.create_new_message(
                Message(user_id=user.id, role=MessageRole.user, content=request_message)
            )
            return JSONResponse(
                content={"status": "ok"},
                status_code=200,
            )

        if user.state == UserState.active:
            # In this scenario the user is active so they are directed to the LLM
            response_messages = await llm_client.generate_response(
                user=user, message=user_message.content
            )

            if response_messages:
                # Update the database with the responses (including tool calls)
                response_messages = await db.create_new_messages(response_messages)

                # Send the last message back to the user
                logger.debug(
                    f"Sending message to {user.wa_id}: {response_messages[-1].content}"
                )
                payload = generate_payload(user.wa_id, response_messages[-1].content)
                await whatsapp_client.send_message(payload)

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
