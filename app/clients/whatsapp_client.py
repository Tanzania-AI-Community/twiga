import asyncio
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, PlainTextResponse

from app.config import settings
from app.models.image_models import DownloadedImage, ImageInputError
from app.monitoring.metrics import record_whatsapp_event
from app.utils.image_utils import MAX_IMAGE_BYTES, SUPPORTED_IMAGE_TYPES, validate_image
from app.utils.logging_utils import log_httpx_response, private_media_logging
from app.utils.whatsapp_utils import (
    generate_payload,
    generate_payload_for_document,
    generate_payload_for_image,
    split_text_for_whatsapp,
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
    _MAX_TEXT_LENGTH_CHARS = 4096
    _MAX_AUDIO_SIZE_BYTES = 16 * 1024 * 1024

    def __init__(self):
        token = settings.whatsapp_api_token.get_secret_value()
        self.url = f"https://graph.facebook.com/{settings.meta_api_version}/{settings.whatsapp_cloud_number_id}"
        if settings.mock_whatsapp:
            assert settings.mock_whatsapp_api_url and settings.mock_whatsapp_token
            self.url = settings.mock_whatsapp_api_url.rstrip("/")
            token = settings.mock_whatsapp_token.get_secret_value()
        self.headers = {
            "Content-type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        self.api_version = settings.meta_api_version
        self.logger = logging.getLogger(__name__)
        self.client = httpx.AsyncClient(base_url=self.url)

    async def download_image(self, media_id: str) -> DownloadedImage:
        """Resolve a Meta media ID and stream its bytes, with one transient retry."""
        if settings.mock_whatsapp or not media_id.isascii() or not media_id.isdigit():
            raise ImageInputError()
        with private_media_logging():
            for attempt in range(2):
                try:
                    async with asyncio.timeout(30):
                        url, mime_type = await self._get_image_download_info(media_id)
                        data = await self._download_image_bytes(url)
                        return await asyncio.to_thread(validate_image, data, mime_type)
                except httpx.HTTPStatusError as exc:
                    if attempt == 0 and (
                        exc.response.status_code == 429
                        or exc.response.status_code >= 500
                    ):
                        continue
                    raise ImageInputError() from None
                except (httpx.RequestError, TimeoutError):
                    if attempt == 0:
                        continue
                    raise ImageInputError() from None
                except (KeyError, TypeError, ValueError, httpx.InvalidURL):
                    raise ImageInputError() from None
        raise ImageInputError()

    async def _get_image_download_info(self, media_id: str) -> tuple[httpx.URL, str]:
        metadata_url = (
            f"https://graph.facebook.com/{settings.meta_api_version}/{media_id}"
        )
        response = await self.client.get(
            metadata_url, headers=self.headers, follow_redirects=False, timeout=30
        )
        response.raise_for_status()
        metadata = response.json()
        if not isinstance(metadata, dict):
            raise ImageInputError()
        mime_type = metadata.get("mime_type")
        if mime_type not in SUPPORTED_IMAGE_TYPES.values():
            raise ImageInputError("image_invalid")
        if int(metadata.get("file_size", 0)) > MAX_IMAGE_BYTES:
            raise ImageInputError("image_invalid")
        return self._validate_image_download_url(metadata["url"]), mime_type

    @staticmethod
    def _validate_image_download_url(value: str) -> httpx.URL:
        url = httpx.URL(value)
        if url.scheme != "https" or url.userinfo or url.port not in (None, 443):
            raise ImageInputError()
        # Only send the access token to Meta's media hosts.
        allowed_hosts = ("facebook.com", "fbcdn.net", "fbsbx.com")
        if not any(
            url.host == host or url.host.endswith("." + host) for host in allowed_hosts
        ):
            raise ImageInputError()
        return url

    async def _download_image_bytes(self, url: httpx.URL) -> bytes:
        async with self.client.stream(
            "GET", url, headers=self.headers, follow_redirects=False, timeout=30
        ) as response:
            response.raise_for_status()
            if int(response.headers.get("content-length", 0)) > MAX_IMAGE_BYTES:
                raise ImageInputError("image_invalid")
            data = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                data.extend(chunk)
                if len(data) > MAX_IMAGE_BYTES:
                    raise ImageInputError("image_invalid")
            return bytes(data)

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Download inbound WhatsApp media after resolving its temporary URL."""
        auth_headers = {"Authorization": self.headers["Authorization"]}
        metadata_response = await self.client.get(
            f"https://graph.facebook.com/{self.api_version}/{media_id}",
            headers=auth_headers,
        )
        metadata_response.raise_for_status()
        metadata = metadata_response.json()

        media_url = metadata.get("url")
        if not media_url:
            raise ValueError("WhatsApp media response did not include a download URL")

        file_size = int(metadata.get("file_size") or 0)
        if file_size > self._MAX_AUDIO_SIZE_BYTES:
            raise ValueError("WhatsApp audio exceeds the 16 MB limit")

        media_response = await self.client.get(media_url, headers=auth_headers)
        media_response.raise_for_status()
        if len(media_response.content) > self._MAX_AUDIO_SIZE_BYTES:
            raise ValueError("WhatsApp audio exceeds the 16 MB limit")

        return media_response.content, metadata.get("mime_type") or "audio/ogg"

    async def send_message(self, wa_id: str, message: str) -> bool:
        i, total = 0, 0
        try:
            # Margin: Meta may count emoji as 2 chars (UTF-16 units)
            safe_limit = self._MAX_TEXT_LENGTH_CHARS - 96
            chunks: list[str] = split_text_for_whatsapp(message, max_length=safe_limit)
            total = len(chunks)

            for i, chunk in enumerate(chunks, start=1):
                payload: dict[str, Any] = generate_payload(wa_id, chunk)
                # The local mock reads JSON; Meta keeps its existing form encoding
                body = (
                    {"json": jsonable_encoder(payload)}
                    if settings.mock_whatsapp
                    else {"data": payload}
                )
                response = await self.client.post(
                    "/messages", headers=self.headers, **body
                )

                log_httpx_response(response)
                response.raise_for_status()

            return True

        except httpx.HTTPStatusError as e:
            self.logger.error(
                f"WhatsApp rejected message for {wa_id} (chunk {i}/{total}, "
                f"status {e.response.status_code}): {e.response.text}"
            )
            record_whatsapp_event(f"send_failed:{e.response.status_code}")
        except httpx.RequestError as e:
            self.logger.error(
                f"WhatsApp request error for {wa_id} (chunk {i}/{total}): {e}"
            )
            record_whatsapp_event("send_failed:request_error")
        except Exception as e:
            self.logger.error(
                f"Unexpected error sending to {wa_id} (chunk {i}/{total}): {e}"
            )
            record_whatsapp_event("send_failed:unexpected")
        return False

    async def send_read_receipt_with_typing_indicator(self, message_id: str) -> None:
        """
        Mark an inbound message as read and show WhatsApp typing indicator.
        Note: this action marks the referenced message (and possibly earlier thread
        messages) as read on WhatsApp. The typing indicator will be shown until we
        send a message or 25 seconds have passed.

        https://developers.facebook.com/documentation/business-messaging/whatsapp/typing-indicators/
        """
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

    def handle_ignored_flow_webhook(self, kind: str) -> JSONResponse:
        """
        Acknowledge WhatsApp Flow webhooks without acting on them.

        Twiga no longer uses Flows, but Meta keeps sending status events until the
        published Flows are deprecated, and a teacher may still submit a form that
        was open on their phone. Acknowledging with 200 stops Meta from retrying.
        """
        self.logger.info("Ignoring WhatsApp Flow webhook: %s", kind)
        record_whatsapp_event(f"flow_ignored:{kind}")
        return JSONResponse(content={"status": "ignored"}, status_code=200)

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
