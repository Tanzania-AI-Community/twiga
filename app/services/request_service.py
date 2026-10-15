import base64
import binascii
import json
import logging

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse

import app.database.db as db
import app.database.enums as enums
from app.clients.whatsapp_client import whatsapp_client
from app.config import Environment, settings
from app.monitoring.metrics import record_whatsapp_event
from app.services.audio_transcription_service import audio_transcription_service
from app.services.state_service import state_client
from app.utils.whatsapp_utils import (
    RequestType,
    extract_message,
    extract_message_info,
    get_request_type,
)

logger = logging.getLogger(__name__)
_MAX_MOCK_AUDIO_BYTES = 16 * 1024 * 1024


def _decode_mock_audio(audio_data: str) -> bytes:
    max_encoded_length = ((_MAX_MOCK_AUDIO_BYTES + 2) // 3) * 4
    if len(audio_data) > max_encoded_length:
        raise ValueError("Mock audio exceeds the 16 MB limit")
    try:
        audio = base64.b64decode(audio_data, validate=True)
    except binascii.Error as exc:
        raise ValueError("Mock audio is not valid base64") from exc
    if len(audio) > _MAX_MOCK_AUDIO_BYTES:
        raise ValueError("Mock audio exceeds the 16 MB limit")
    return audio


async def handle_request(request: Request) -> JSONResponse:
    """
    Handles HTTP requests to the 'webhooks' and 'flows' endpoints.
    """
    try:
        body = await request.json()

        request_type = get_request_type(body)
        record_whatsapp_event(request_type.name.lower())
        logger.info(f"Received a request of type: {request_type}")

        # Route the basic and stateless request types
        match request_type:
            case RequestType.FLOW_EVENT:
                return whatsapp_client.handle_flow_event(body)
            case RequestType.MESSAGE_STATUS_UPDATE:
                return whatsapp_client.handle_status_update(body)
            case RequestType.FLOW_COMPLETE:
                return await whatsapp_client.handle_flow_message_complete(body)
            case RequestType.INVALID_MESSAGE:
                return whatsapp_client.handle_invalid_message(body)
            case RequestType.OUTDATED:
                return whatsapp_client.handle_outdated_message(body)
            case RequestType.VALID_MESSAGE:
                return await handle_valid_message(body)

        raise Exception(f"Invalid request type. This is the request body: {body}")
    except json.JSONDecodeError:
        record_whatsapp_event("invalid_json")
        logger.error("Failed to decode JSON")
        return JSONResponse(
            content={"status": "error", "message": "Invalid JSON provided"},
            status_code=400,
        )
    except Exception as e:
        record_whatsapp_event("internal_error")
        logger.error(f"Unexpected error in webhook handler: {str(e)}")
        return JSONResponse(
            content={"status": "error", "message": "Internal server error"},
            status_code=500,
        )


async def handle_valid_message(body: dict) -> JSONResponse:
    # Extract message information
    message_info = extract_message_info(body)
    message = message_info.get("message") or {}
    if message.get("type") == "audio":
        media_id = message.get("audio", {}).get("id")
        if not media_id:
            return JSONResponse(
                content={"status": "error", "message": "Invalid audio message"},
                status_code=400,
            )
        try:
            audio_payload = message.get("audio", {})
            inline_audio = audio_payload.get("data")
            if settings.mock_whatsapp and inline_audio:
                audio = _decode_mock_audio(inline_audio)
                mime_type = audio_payload.get("mime_type") or "audio/ogg"
            else:
                audio, mime_type = await whatsapp_client.download_media(media_id)
            provider_override = audio_payload.get("transcription_provider")
            model_override = audio_payload.get("transcription_model")
            if (provider_override or model_override) and not (
                settings.mock_whatsapp
                and settings.environment in (Environment.LOCAL, Environment.DEVELOPMENT)
            ):
                raise ValueError(
                    "Audio transcription overrides are only available in local "
                    "mock WhatsApp mode"
                )
            transcription = await audio_transcription_service.transcribe(
                audio,
                mime_type,
                provider=provider_override,
                model=model_override,
            )
            message_content = transcription.text
            message_info["transcription_metadata"] = {
                "provider": transcription.provider.value,
                "model": transcription.model,
                "latency_ms": transcription.latency_ms,
            }
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to transcribe inbound WhatsApp audio")
            await whatsapp_client.send_message(
                message_info["wa_id"],
                "Samahani, sikuweza kusoma ujumbe wako wa sauti. Tafadhali "
                "jaribu tena au utume ujumbe wa maandishi.",
            )
            return JSONResponse(content={"status": "ok"}, status_code=200)
    else:
        message_content = extract_message(message)

    if not message_content:
        logger.warning("Empty message received")
        return JSONResponse(
            content={"status": "error", "message": "Invalid message"},
            status_code=400,
        )

    # Store extracted message content in message_info for use downstream
    message_info["extracted_content"] = message_content

    # Main message routing logic
    response = await handle_chat_message(message_info["wa_id"], message_info)
    transcription_metadata = message_info.get("transcription_metadata")
    if transcription_metadata:
        response.headers["X-Audio-Transcription-Provider"] = transcription_metadata[
            "provider"
        ]
        response.headers["X-Audio-Transcription-Model"] = transcription_metadata[
            "model"
        ]
        response.headers["X-Audio-Transcription-Latency-Ms"] = str(
            transcription_metadata["latency_ms"]
        )
    return response


async def handle_chat_message(phone_number: str, message_info: dict) -> JSONResponse:
    """Main entry point for handling all valid WhatsApp messages based on user state

    Fetch all data upfront with one method.
    All data is loaded while session is open, then used from memory.
    """

    # Fetch user with FULL data (one method does everything)
    user = await db.get_user_by_waid(phone_number)

    if not user:
        # New user - start registration/onboarding flow
        return await state_client.handle_new_user_registration(
            phone_number, message_info
        )

    if user.id is None:
        raise ValueError(
            "User ID is unexpectedly None after fetching user from database."
        )

    user_message = await db.create_new_message_by_fields(
        user_id=user.id,
        role=enums.MessageRole.user,
        content=message_info.get("extracted_content", ""),
        is_present_in_conversation=True,
    )

    # Handle rate limiting
    rate_limit_response = await state_client._handle_rate_limiting(user, phone_number)
    if rate_limit_response:
        return rate_limit_response

    # Route based on user state
    match user.state:
        case enums.UserState.blocked:
            return await state_client.handle_blocked(user)

        case enums.UserState.in_review:
            return await state_client.handle_in_review_user(user)

        case enums.UserState.approved:
            # Users approved by dashboard - send welcome message and transition to onboarding
            # Send welcome message and move user to onboarding state
            welcome_response = await state_client.handle_new_approved_user(user)
            return welcome_response

        case enums.UserState.inactive:
            # Reactivate user
            reactivate_response = await state_client.handle_inactive_user(user)
            if reactivate_response.status_code != 200:
                return reactivate_response

            # Process their message
            return await state_client.handle_active(user, message_info, user_message)

        case enums.UserState.onboarding:
            # Message already persisted above
            return await state_client.handle_onboarding(user)

        case enums.UserState.active:
            return await state_client.handle_active(user, message_info, user_message)

        case _:
            logger.warning(f"Unknown user state: {user.state}")
            return JSONResponse(content={"status": "error"}, status_code=400)
