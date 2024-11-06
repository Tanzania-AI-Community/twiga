import json
import logging
from typing import List, Optional
from fastapi import Request
from fastapi.responses import JSONResponse

from app.database.models import Message, MessageRole, User, UserState
from app.utils.whatsapp_utils import (
    COMMAND_OPTIONS,
    extract_message_body,
    extract_message_info,
    generate_payload,
    get_text_payload,
    is_message_recent,
    is_status_update,
    is_whatsapp_user_message,
    is_flow_complete_message,
    is_event,
    is_interactive_message,
    is_command_message,
)

from app.services.whatsapp_service import whatsapp_client
from app.services.llm_service import llm_client
from app.services.flow_service import flow_client
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
        logger.debug(f"Received message on webhook: {body}")

        # TODO: All of these cases can be handled within one separate function to shorten this function
        # Handle different types of events
        if is_event(body):
            return await whatsapp_client.handle_event_request(body)

        # Check if it's a WhatsApp status update (sent, delivered, read)
        if is_status_update(body):
            return whatsapp_client.handle_status_update(body)

        # Process non-status updates (message, other)
        if not is_whatsapp_user_message(body):
            logger.warning("Received a non-WhatsApp user message. Ignoring. %s", body)
            return JSONResponse(
                content={"status": "error", "message": "Not a WhatsApp API event"},
                status_code=404,
            )
        # Check if it's a flow completion message # Merge this with the status update
        if is_flow_complete_message(body):
            logger.debug("Received a flow completion message. Ignoring. %s", body)
            return JSONResponse(
                content={"status": "ok"},
                status_code=200,
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

        if is_interactive_message(message_info):
            # Handle interactive message
            return await handle_interactive(user, message_info)

        if is_command_message(message_info):
            message = message_info.get("message", {}).get("text", {}).get("body", "")
            return await handle_command_message(user, message)

        # Handle state using the State Service
        response_text, options, is_end, updated_user = await state_client.process_state(
            user
        )

        if updated_user:
            user = updated_user

        # TODO: Fix "is_end", I'm not a fan of it - Victor
        logger.debug(f"Response text: {response_text} | Options: {options}")
        if is_end:
            return JSONResponse(
                content={"status": "ok"},
                status_code=200,
            )

        request_message = extract_message_body(message_info["message"])

        user_message = await db.create_new_message(
            Message(user_id=user.id, role=MessageRole.user, content=request_message)
        )

        if response_text:
            # In this scenario the user is in a state that had a predefined response
            payload = generate_payload(user.wa_id, response_text, options)
            await whatsapp_client.send_message(payload)

            # Store the bot response in the database
            await db.create_new_message(
                Message(
                    user_id=user.id, role=MessageRole.assistant, content=response_text
                )
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


async def handle_interactive(user: User, message_info: dict) -> JSONResponse:
    try:
        # Extract the title from the message using extract_message_body
        title = extract_message_body(message_info.get("message", {}))
        logger.info(f"Handling interactive message with title: {title}")

        if title == "Personal Info":
            logger.info("Sending update personal and school info flow")
            await flow_client.send_update_personal_and_school_info_flow(user)
        elif title == "Class and Subject":
            logger.info("Sending update class and subject info flow")
            await flow_client.send_update_class_and_subject_info_flow(user)
        else:
            # Say reply not recognized
            response_text = "Your reply was not recognized. Please try another."
            logger.warning(f"Unrecognized reply: {title}")
            await whatsapp_client.send_message(
                get_text_payload(user.wa_id, response_text)
            )
            return JSONResponse(
                content={"status": "ok"},
                status_code=200,
            )

        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )
    except Exception as e:
        logger.error(f"Error handling interactive message: {e}")
        return JSONResponse(
            content={"status": "error", "message": str(e)},
            status_code=500,
        )


async def handle_command_message(user: User, message: str) -> JSONResponse:  # type: ignore
    logger.info(f"Handling command message: {message}")
    try:
        if message == "settings":
            # send interactive message to the user showing them the options for settings
            response_text = (
                "Welcome to the Settings Menu, please select what you want to update"
            )
            options = ["Personal Info", "Class and Subject"]
            payload = generate_payload(user.wa_id, response_text, options)

            return await whatsapp_client.send_message(payload)
        else:
            # handle other commands or provide a default response
            response_text = "Command not recognized. Please try again."
            await whatsapp_client.send_message(
                generate_payload(user.wa_id, response_text, [])
            )

    except Exception as e:
        logger.error(f"Error handling command message: {e}")
        return JSONResponse(
            content={"status": "error", "message": str(e)},
            status_code=500,
        )
