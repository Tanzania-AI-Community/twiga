from fastapi import Request
from fastapi.responses import PlainTextResponse, JSONResponse
import logging

import httpx

from app.config import settings
from app.utils.logging_utils import log_httpx_response


class WhatsAppClient:
    def __init__(self):
        self.headers = {
            "Content-type": "application/json",
            "Authorization": f"Bearer {settings.whatsapp_api_token.get_secret_value()}",
        }
        self.url = f"https://graph.facebook.com/{settings.meta_api_version}/{settings.whatsapp_cloud_number_id}"
        self.logger = logging.getLogger(__name__)
        self.client = httpx.AsyncClient(base_url=self.url)

    async def send_message(self, payload: str) -> None:
        try:
            response = await self.client.post(
                "/messages", data=payload, headers=self.headers
            )
            log_httpx_response(response)
        except httpx.RequestError as e:
            self.logger.error("Request Error: %s", e)
        except Exception as e:
            self.logger.error("Unexpected Error: %s", e)

    def verify(self, request: Request):
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

        if (
            mode == "subscribe"
            and token == settings.whatsapp_verify_token.get_secret_value()
        ):
            self.logger.info("WEBHOOK_VERIFIED")
            return PlainTextResponse(content=challenge)

        self.logger.error("VERIFICATION_FAILED")
        return JSONResponse(
            content={"status": "error", "message": "Verification failed"},
            status_code=403,
        )

    def handle_status_update(self, body: dict) -> JSONResponse:
        """
        Handles WhatsApp status updates (sent, delivered, read).
        """
        self.logger.debug(
            f"Received a WhatsApp status update: {body.get('entry', [{}])[0].get('changes', [{}])[0].get('value', {}).get('statuses')}"
        )
        return JSONResponse(content={"status": "ok"}, status_code=200)


whatsapp_client = WhatsAppClient()
