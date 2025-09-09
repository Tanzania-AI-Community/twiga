from typing import Any, Dict, List, Optional
from fastapi import Request
from fastapi.responses import PlainTextResponse, JSONResponse
import logging

import httpx

from app.config import settings
from app.utils.logging_utils import log_httpx_response
from app.utils.whatsapp_utils import generate_payload


class WhatsAppClient:
    def __init__(self):
        self.headers = {
            "Content-type": "application/json",
            "Authorization": f"Bearer {settings.whatsapp_api_token.get_secret_value()}",
        }
        self.url = f"https://graph.facebook.com/{settings.meta_api_version}/{settings.whatsapp_cloud_number_id}"
        self.logger = logging.getLogger(__name__)
        self.client = httpx.AsyncClient(base_url=self.url)

    async def send_message(
        self, wa_id: str, message: str, options: Optional[List[str]] = None
    ) -> None:

        if settings.mock_whatsapp:
            return

        try:
            payload: Dict[str, Any] = generate_payload(wa_id, message, options)
            response = await self.client.post(
                "/messages", data=payload, headers=self.headers
            )
            log_httpx_response(response)
        except httpx.RequestError as e:
            self.logger.error("Request Error: %s", e)
        except Exception as e:
            self.logger.error("Unexpected Error: %s", e)

    async def send_template_message(
        self, wa_id: str, template_name: str, language_code: str = "en"
    ) -> None:
        """
        Send a WhatsApp template message with image header.
        """
        if settings.mock_whatsapp:
            return

        try:
            # Create payload with image header for template
            payload: Dict[str, Any] = {
                "messaging_product": "whatsapp",
                "to": wa_id,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": language_code},
                    "components": [
                        {
                            "type": "header",
                            "parameters": [
                                {
                                    "type": "image",
                                    "image": {
                                        "link": "https://private-user-images.githubusercontent.com/21913954/349197215-de0cc88b-b75f-43aa-850c-34c1315a5980.png?jwt=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJnaXRodWIuY29tIiwiYXVkIjoicmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbSIsImtleSI6ImtleTUiLCJleHAiOjE3NTc0MDU0NzMsIm5iZiI6MTc1NzQwNTE3MywicGF0aCI6Ii8yMTkxMzk1NC8zNDkxOTcyMTUtZGUwY2M4OGItYjc1Zi00M2FhLTg1MGMtMzRjMTMxNWE1OTgwLnBuZz9YLUFtei1BbGdvcml0aG09QVdTNC1ITUFDLVNIQTI1NiZYLUFtei1DcmVkZW50aWFsPUFLSUFWQ09EWUxTQTUzUFFLNFpBJTJGMjAyNTA5MDklMkZ1cy1lYXN0LTElMkZzMyUyRmF3czRfcmVxdWVzdCZYLUFtei1EYXRlPTIwMjUwOTA5VDA4MDYxM1omWC1BbXotRXhwaXJlcz0zMDAmWC1BbXotU2lnbmF0dXJlPWFmOGI2NzY1MzQyZTA5YjkzN2U5NDBlNGM0MWU5N2IyODQ4YzU0NGM0Zjg5OTUxOTgwMDc1NTljOWVhMGM4Y2QmWC1BbXotU2lnbmVkSGVhZGVycz1ob3N0In0.av3Z8fq9vxSZmZfPT9eXUKmp7zKU56YGUYRP_wxYGFw"
                                    },
                                }
                            ],
                        }
                    ],
                },
            }

            response = await self.client.post(
                "/messages", json=payload, headers=self.headers
            )
            log_httpx_response(response)
        except httpx.RequestError as e:
            self.logger.error("Template Message Request Error: %s", e)
        except Exception as e:
            self.logger.error("Template Message Unexpected Error: %s", e)

    def verify(self, request: Request) -> JSONResponse | PlainTextResponse:
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

    def handle_outdated_message(self, body: dict) -> JSONResponse:
        self.logger.warning("Received a message with an outdated timestamp. Ignoring.")
        return JSONResponse(
            content={"status": "error", "message": "Message is outdated"},
            status_code=400,
        )

    def handle_status_update(self, body: dict) -> JSONResponse:
        """
        Handles WhatsApp status updates (sent, delivered, read).
        """
        self.logger.debug(
            f"Received a WhatsApp status update: {body.get('entry', [{}])[0].get('changes', [{}])[0].get('value', {}).get('statuses')}"
        )
        return JSONResponse(content={"status": "ok"}, status_code=200)

    def handle_flow_event(self, body: dict) -> JSONResponse:
        """
        Handles WhatsApp webhook events.
        """
        self.logger.debug(f"Received a WhatsApp Flow event: {body}")
        event_type = body["entry"][0]["changes"][0]["value"]["event"]

        if event_type == "ENDPOINT_AVAILABILITY":
            flow_id = body["entry"][0]["changes"][0]["value"]["flow_id"]
            threshold = body["entry"][0]["changes"][0]["value"]["threshold"]
            availability = body["entry"][0]["changes"][0]["value"]["availability"]
            self.logger.info(
                f"Received a flow availability request for flow id {flow_id}, threshold {threshold}, availability {availability}"
            )
            return JSONResponse(
                content={"status": "ok"},
                status_code=200,
            )
        elif event_type == "FLOW_STATUS_CHANGE":
            flow_id = body["entry"][0]["changes"][0]["value"]["flow_id"]
            old_status = body["entry"][0]["changes"][0]["value"]["old_status"]
            new_status = body["entry"][0]["changes"][0]["value"]["new_status"]
            self.logger.info(
                f"Received a flow status change request for flow id {flow_id}, old status {old_status}, new status {new_status}"
            )
            return JSONResponse(
                content={"status": "ok"},
                status_code=200,
            )
        elif event_type == "ENDPOINT_ERROR_RATE":
            self.logger.info(f"Handling event type: {event_type}")
            # Add your handling logic here
            return JSONResponse(
                content={
                    "status": "success",
                    "message": f"Handled event type: {event_type}",
                },
                status_code=200,
            )
        elif event_type == "ENDPOINT_LATENCY":
            self.logger.info(f"Handling event type: {event_type}")
            # Add your handling logic here
            return JSONResponse(
                content={
                    "status": "success",
                    "message": f"Handled event type: {event_type}",
                },
                status_code=200,
            )
        else:
            self.logger.warning(f"⚠️ Unhandled event type: {event_type}")
            return JSONResponse(
                content={
                    "status": "warning",
                    "message": f"Unhandled event type: {event_type}",
                },
                status_code=200,
            )

    def handle_flow_message_complete(self, body: dict) -> JSONResponse:
        """
        Handles WhatsApp flow message completion events.
        """
        self.logger.debug(
            f"Received a WhatsApp Flow message complete event. Ignoring: {body}"
        )
        return JSONResponse(content={"status": "ok"}, status_code=200)

    def handle_invalid_message(self, body: dict) -> JSONResponse:
        """
        Handles invalid WhatsApp messages.
        """
        self.logger.error(f"Received an invalid WhatsApp message: {body}")
        return JSONResponse(
            content={"status": "error", "message": "Not a valid WhatsApp API event"},
            status_code=404,
        )


whatsapp_client = WhatsAppClient()
