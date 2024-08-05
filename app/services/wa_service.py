from fastapi import Request
from fastapi.responses import JSONResponse
import json
import logging

from app.config import settings
from app.services.messaging_service import process_message
from app.utils.whatsapp_utils import (
    extract_message_info,
    get_text_payload,
    is_message_recent,
    is_status_update,
    is_valid_whatsapp_message,
    send_message,
)
from db.utils import store_message, is_rate_limit_reached


class WhatsAppClient:
    def __init__(self):
        self.headers = {
            "Content-type": "application/json",
            "Authorization": f"Bearer {settings.whatsapp_api_token.get_secret_value()}",
        }
        self.url = f"https://graph.facebook.com/{settings.meta_api_version}/{settings.whatsapp_cloud_number_id}"
        self.logger = logging.getLogger(__name__)

    def verify(self, request: Request) -> JSONResponse:
        """
        Verifies the webhook for WhatsApp. This is required.
        """

        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        if not mode or not token:
            self.logger.error("MISSING_PARAMETER")
            return JSONResponse(
                content={"status": "error", "message": "Missing parameters"},
                status_code=400,
            )

        if mode == "subscribe" and token == settings.whatsapp_verify_token:
            self.logger.info("WEBHOOK_VERIFIED")
            return JSONResponse(
                content={"status": "success", "challenge": challenge},
                status_code=200,
            )
        elif mode == "subscribe" and token != settings.whatsapp_verify_token:
            self.logger.error("VERIFICATION_FAILED")
            return JSONResponse(
                content={"status": "error", "message": "Verification failed"},
                status_code=403,
            )
        else:  # Responds with '400 Bad Request' if the mode is not 'subscribe'
            self.logger.error("INVALID_MODE")
            return JSONResponse(
                content={"status": "error", "message": "Invalid mode"},
                status_code=400,
            )

    def _handle_status_update(self, body: dict) -> JSONResponse:
        """
        Handles WhatsApp status updates (sent, delivered, read).
        """
        self.logger.debug(
            f"Received a WhatsApp status update: {body.get('entry', [{}])[0].get('changes', [{}])[0].get('value', {}).get('statuses')}"
        )
        return JSONResponse(content={"status": "ok"}, status_code=200)

    async def _handle_rate_limit(self, wa_id: str, message: dict) -> JSONResponse:
        # TODO: This is a good place to use a template instead of hardcoding the message
        self.logger.warning("Message limit reached for wa_id: %s", wa_id)
        sleepy_text = (
            "🚫 You have reached your daily messaging limit, so Twiga 🦒 is quite sleepy 🥱 "
            "from all of today's texting. Let's talk more tomorrow!"
        )
        data = get_text_payload(wa_id, sleepy_text)
        store_message(wa_id, message, role="user")
        await send_message(data)
        return JSONResponse(content={"status": "ok"}, status_code=200)

    async def handle_request(self, request: Request) -> JSONResponse:
        """
        Handles HTTP requests to this webhook for message, sent, delivered, and read events.
        """
        body = await request.json()

        # Check if it's a WhatsApp status update (sent, delivered, read)
        if is_status_update(body):
            return self._handle_status_update(body)

        # Process non-status updates (message, other)
        try:
            if not is_valid_whatsapp_message(body):
                return JSONResponse(
                    content={"status": "error", "message": "Not a WhatsApp API event"},
                    status_code=404,
                )

            message_info = extract_message_info(body)
            wa_id = message_info["wa_id"]
            message = message_info["message"]
            timestamp = message_info["timestamp"]
            name = message_info["name"]

            # TODO: Figure out a better way to handle rate limiting and what to do with older messages
            if is_message_recent(timestamp):
                if is_rate_limit_reached(wa_id):
                    return await self._handle_rate_limit(wa_id, message)

                generated_response = await process_message(
                    wa_id, name, message, timestamp
                )
                await send_message(generated_response)
                return JSONResponse(content={"status": "ok"}, status_code=200)
            else:
                store_message(wa_id, message, role="user")
                self.logger.warning("Received a message with an outdated timestamp.")
                return JSONResponse(content={"status": "ok"}, status_code=200)
        except json.JSONDecodeError:
            self.logger.error("Failed to decode JSON")
            return JSONResponse(
                content={"status": "error", "message": "Invalid JSON provided"},
                status_code=400,
            )


whatsapp_client = WhatsAppClient()
