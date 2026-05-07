import json
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse

import app.database.db as db
import app.database.enums as enums
import app.services.flows.utils as flow_utils
from app.config import settings
from app.database.models import User
from app.monitoring.metrics import record_whatsapp_event
from app.utils.logging_utils import log_httpx_response
from app.utils.string_manager import StringCategory, strings
from app.utils.whatsapp_utils import (
    generate_payload,
    generate_payload_for_document,
    generate_payload_for_image,
)


class ImageType(str, Enum):
    JPEG = "image/jpeg"
    PNG = "image/png"
    JPG = "image/jpeg"


class DocumentType(str, Enum):
    PDF = "application/pdf"


def _extract_statuses(body: dict) -> list[dict]:
    entry = (body.get("entry") or [{}])[0]
    change = (entry.get("changes") or [{}])[0]
    value = change.get("value") or {}
    return value.get("statuses") or []


class WhatsAppClient:
    _MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
    _MAX_DOCUMENT_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB

    def __init__(self):
        self.headers = {
            "Content-type": "application/json",
            "Authorization": f"Bearer {settings.whatsapp_api_token.get_secret_value()}",
        }
        self.url = f"https://graph.facebook.com/{settings.meta_api_version}/{settings.whatsapp_cloud_number_id}"
        self.logger = logging.getLogger(__name__)
        self.client = httpx.AsyncClient(base_url=self.url)

    async def send_message(
        self, wa_id: str, message: str, options: list[str] | None = None
    ) -> None:
        if settings.mock_whatsapp:
            return

        try:
            payload: dict[str, Any] = generate_payload(wa_id, message, options)
            response = await self.client.post(
                "/messages", data=payload, headers=self.headers
            )
            log_httpx_response(response)
        except httpx.RequestError as e:
            self.logger.error(f"Request Error: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected Error: {e}")

    async def send_read_receipt_with_typing_indicator(self, message_id: str) -> None:
        """
        Mark an inbound message as read and show WhatsApp typing indicator.
        Note: this action marks the referenced message (and possibly earlier thread
        messages) as read on WhatsApp. The typing indicator will be shown until we
        send a message or 25 seconds have passed.

        https://developers.facebook.com/documentation/business-messaging/whatsapp/typing-indicators/
        """
        if settings.mock_whatsapp:
            return

        if not message_id:
            self.logger.warning(
                "Skipping WhatsApp typing indicator because inbound message id is empty."
            )
            return

        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
            "typing_indicator": {"type": "text"},
        }

        try:
            response = await self.client.post(
                "/messages", json=payload, headers=self.headers
            )
            log_httpx_response(response)
        except httpx.RequestError as e:
            self.logger.error(f"Typing Indicator Request Error: {e}")
        except Exception as e:
            self.logger.error(f"Typing Indicator Unexpected Error: {e}")

    async def send_whatsapp_flow_message(
        self,
        user: User,
        flow_id: str,
        header_text: str,
        body_text: str,
        action_payload: dict[str, Any],
        flow_cta: str,
        mode: str = "published",
    ) -> None:
        if settings.mock_whatsapp:
            return

        flow_token = flow_utils.encrypt_flow_token(user.wa_id, flow_id)

        payload = {
            "messaging_product": "whatsapp",
            "to": user.wa_id,
            "recipient_type": "individual",
            "type": "interactive",
            "interactive": {
                "type": "flow",
                "header": {
                    "type": "text",
                    "text": header_text,
                },
                "body": {
                    "text": body_text,
                },
                "footer": {
                    "text": strings.get_string(
                        StringCategory.FLOWS, "flow_footer_text"
                    ),
                },
                "action": {
                    "name": "flow",
                    "parameters": {
                        "flow_message_version": "3",
                        "flow_action": "navigate",
                        "flow_token": flow_token,
                        "flow_id": flow_id,
                        "flow_cta": flow_cta,
                        "mode": mode,
                        "flow_action_payload": action_payload,
                    },
                },
            },
        }

        try:
            response = await self.client.post(
                "/messages", json=payload, headers=self.headers
            )
            log_httpx_response(response)
        except httpx.RequestError as e:
            self.logger.error(f"Flow Message Request Error: {e}")
        except Exception as e:
            self.logger.error(f"Flow Message Unexpected Error: {e}")

    async def send_image_message(
        self,
        wa_id: str,
        image_path: str,
        img_type: ImageType,
        caption: str | None = None,
    ) -> bool:
        if settings.mock_whatsapp:
            self.logger.info(
                f"Mock send_image_message called for {wa_id} with image {image_path}"
            )
            return True

        media_id: str | None = None

        try:
            media_id = await self.upload_media(
                image_path,
                mime_type=img_type.value,
                max_size_bytes=self._MAX_IMAGE_SIZE_BYTES,
            )

            if not media_id:
                raise ValueError(
                    "Failed to retrieve media id for WhatsApp image message."
                )

            payload = generate_payload_for_image(
                wa_id=wa_id, media_id=media_id, caption=caption
            )

            response = await self.client.post(
                "/messages", json=payload, headers=self.headers
            )
            log_httpx_response(response)
            response.raise_for_status()
            return True

        except httpx.RequestError as e:
            self.logger.error(f"Image Message Request Error: {e}")

        except Exception as e:
            self.logger.error(f"Image Message Unexpected Error: {e}")

        finally:
            if media_id:
                try:
                    await self.delete_media(
                        media_id, image_path
                    )  # Clean up uploaded media and local file
                except Exception as exc:
                    self.logger.warning(
                        f"Image cleanup failed for media {media_id} ({image_path}): {exc}"
                    )
            else:
                self._delete_local_file(image_path)

        return False

    async def send_document_message(
        self,
        wa_id: str,
        document_path: str,
        doc_type: DocumentType = DocumentType.PDF,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
        delete_local_file: bool = False,
    ) -> bool:
        if settings.mock_whatsapp:
            self.logger.info(
                f"Mock send_document_message called for {wa_id} with document {document_path}"
            )
            return True

        media_id: Optional[str] = None

        try:
            media_id = await self.upload_media(
                document_path,
                mime_type=doc_type.value,
                max_size_bytes=self._MAX_DOCUMENT_SIZE_BYTES,
            )

            if not media_id:
                raise ValueError(
                    "Failed to retrieve media id for WhatsApp document message."
                )

            payload = generate_payload_for_document(
                wa_id=wa_id,
                media_id=media_id,
                caption=caption,
                filename=filename,
            )

            response = await self.client.post(
                "/messages", json=payload, headers=self.headers
            )
            log_httpx_response(response)
            response.raise_for_status()
            return True
        except httpx.RequestError as e:
            self.logger.error(f"Document Message Request Error: {e}")
        except Exception as e:
            self.logger.error(f"Document Message Unexpected Error: {e}")
        finally:
            if media_id:
                try:
                    await self.delete_media(
                        media_id,
                        document_path,
                        delete_local_file=delete_local_file,
                    )
                except Exception as exc:
                    self.logger.warning(
                        f"Document cleanup failed for media {media_id} ({document_path}): {exc}"
                    )
            elif delete_local_file:
                self._delete_local_file(document_path)

        return False

    async def delete_media(
        self, media_id: str, image_path: str, delete_local_file: bool = True
    ) -> None:
        """Delete upload media from WhatsApp and locally"""
        if settings.mock_whatsapp:
            return

        try:
            headers = {
                "Authorization": self.headers["Authorization"],
            }
            url = f"https://graph.facebook.com/{settings.meta_api_version}/{media_id}"
            response = await self.client.delete(url, headers=headers)
            log_httpx_response(response)
            response.raise_for_status()
        except httpx.RequestError as e:
            self.logger.error(f"Media Delete Request Error: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Media Delete Unexpected Error: {e}")
            raise
        finally:
            if delete_local_file:
                self._delete_local_file(image_path)

    def _delete_local_file(self, image_path: str) -> None:
        try:
            if os.path.exists(image_path):
                os.remove(image_path)
        except Exception as e:
            self.logger.error(f"Failed to delete file {image_path}: {e}")

    async def upload_media(
        self,
        path: str,
        mime_type: str,
        max_size_bytes: int,
    ) -> Optional[str]:
        """Upload media to WhatsApp and return the media ID."""

        if settings.mock_whatsapp:
            return None

        file_path = Path(path)

        if not file_path.is_file():
            raise FileNotFoundError(f"Image file not found at {path}")

        file_size = file_path.stat().st_size
        if file_size > max_size_bytes:
            raise ValueError("Media size exceeds limit for WhatsApp uploads.")

        try:
            with file_path.open("rb") as file_handle:
                files = {
                    "file": (file_path.name, file_handle, mime_type),
                }
                data = {"messaging_product": "whatsapp"}
                headers = {
                    "Authorization": self.headers["Authorization"],
                }
                response = await self.client.post(
                    "/media", data=data, files=files, headers=headers
                )
            log_httpx_response(response)
            response.raise_for_status()
            media_id = response.json().get("id")
            if not media_id:
                raise ValueError(
                    "WhatsApp media upload response did not include an id."
                )
            return media_id
        except httpx.RequestError as e:
            self.logger.error(f"Media Upload Request Error: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Media Upload Unexpected Error: {e}")
            raise

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
            payload: dict[str, Any] = {
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
                                        "link": "https://twiga.ai.or.tz/external/classroom-image.jpeg"
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
            self.logger.error(f"Template Message Request Error: {e}")
        except Exception as e:
            self.logger.error(f"Template Message Unexpected Error: {e}")

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
        record_whatsapp_event("handler:outdated_message")
        return JSONResponse(
            content={"status": "error", "message": "Message is outdated"},
            status_code=400,
        )

    def handle_status_update(self, body: dict) -> JSONResponse:
        """
        Handles WhatsApp status updates (sent, delivered, read).
        """
        self.logger.debug(f"Received a WhatsApp status update: {body}")
        statuses = _extract_statuses(body)
        if statuses:
            status = statuses[0].get("status", "unknown")
            record_whatsapp_event(f"status_update:{status}")
        return JSONResponse(content={"status": "ok"}, status_code=200)

    def handle_flow_event(self, body: dict) -> JSONResponse:
        """
        Handles WhatsApp webhook events.
        """
        self.logger.debug(f"Received a WhatsApp Flow event: {body}")
        event_type = body["entry"][0]["changes"][0]["value"]["event"]
        record_whatsapp_event(f"flow_event:{event_type.lower()}")

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

    async def handle_flow_message_complete(self, body: dict) -> JSONResponse:
        """
        Handles WhatsApp flow message completion events.
        """
        self.logger.debug(f"Received a WhatsApp Flow message complete event: {body}")
        record_whatsapp_event("handler:flow_message_complete")

        try:
            value = body["entry"][0]["changes"][0]["value"]
            wa_id = value["contacts"][0]["wa_id"]
            response_json = value["messages"][0]["interactive"]["nfm_reply"][
                "response_json"
            ]

            if isinstance(response_json, str):
                response_payload = json.loads(response_json)
            else:
                response_payload = response_json

            user = await db.get_user_by_waid(wa_id)
            if user and user.id is not None:
                await db.create_new_message_by_fields(
                    user_id=user.id,
                    role=enums.MessageRole.user,
                    content=f"[FLOW_COMPLETED] {json.dumps(response_payload, default=str)}",
                    is_present_in_conversation=True,
                )
            else:
                self.logger.warning(
                    f"Flow completion received for unknown user with wa_id={wa_id}"
                )
        except Exception as e:
            self.logger.error(f"Failed to persist flow completion payload: {e}")

        return JSONResponse(content={"status": "ok"}, status_code=200)

    def handle_invalid_message(self, body: dict) -> JSONResponse:
        """
        Handles invalid WhatsApp messages.
        """
        self.logger.error(f"Received an invalid WhatsApp message: {body}")
        record_whatsapp_event("handler:invalid_message")
        return JSONResponse(
            content={"status": "error", "message": "Not a valid WhatsApp API event"},
            status_code=404,
        )


whatsapp_client = WhatsAppClient()
