import logging
from fastapi.responses import PlainTextResponse, JSONResponse
from app.utils.flows_util import (
    decrypt_flow_webhook,
    decrypt_flow_token,
    encrypt_flow_token,
)
from app.database.db import get_user_data, update_user
from app.config import settings
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64
import json
import httpx

logger = logging.getLogger(__name__)


class FlowService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def handle_flow_webhook(self, body: dict) -> PlainTextResponse:
        try:
            decrypted_data = decrypt_flow_webhook(body)
            decrypted_payload = decrypted_data["decrypted_payload"]
            aes_key = decrypted_data["aes_key"]
            initial_vector = decrypted_data["initial_vector"]
        except ValueError as e:
            self.logger.error(f"Error decrypting payload: {e}")
            return PlainTextResponse(content="Decryption failed", status_code=421)
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            return PlainTextResponse(content="Decryption failed", status_code=500)

        self.logger.info(f"Flow Webhook Decrypted payload: {decrypted_payload}")
        wa_id, flow_id = decrypt_flow_token(decrypted_payload.get("flow_token"))

        action = decrypted_payload.get("action")
        self.logger.info(f"Flow Action: {action}, Flow ID: {flow_id}")
        handler = self.get_action_handler(action, flow_id)
        return await handler(decrypted_payload, aes_key, initial_vector)

    def get_action_handler(self, action: str, flow_id: str):
        if flow_id == settings.subject_class_info_flow_id:
            return {
                "ping": self.handle_health_check,
                "INIT": self.handle_subject_class_info_init_action,
                "data_exchange": self.handle_subject_class_info_data_exchange_action,
            }.get(action, self.handle_unknown_action)
        else:
            return {
                "ping": self.handle_health_check,
                "INIT": self.handle_personal_and_school_info_flow_init_action,
                "data_exchange": self.handle_personal_and_school_info_flow_data_exchange_action,
            }.get(action, self.handle_unknown_action)

    async def handle_unknown_action(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.warning(
            f"Unknown action received: {decrypted_payload.get('action')}"
        )
        response_payload = {"unknown": "event"}
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_personal_and_school_info_flow_init_action(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        encrypted_flow_token = decrypted_payload.get("flow_token")
        if not encrypted_flow_token:
            self.logger.error("Missing flow token")
            return JSONResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )
        try:
            wa_id, flow_id = decrypt_flow_token(encrypted_flow_token)
        except Exception as e:
            self.logger.error(f"Error decrypting flow token: {e}")
            return JSONResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )

        user_data = await get_user_data(wa_id)
        if not user_data:
            self.logger.error(f"User data not found for wa_id {wa_id}")
            return JSONResponse(
                content={"error_msg": "User data not found"}, status_code=422
            )

        response_payload = {
            "screen": "personal_info",
            "data": {"full_name": user_data.get("name", "Your Name")},
        }
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_subject_class_info_init_action(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        encrypted_flow_token = decrypted_payload.get("flow_token")
        if not encrypted_flow_token:
            self.logger.error("Missing flow token")
            return JSONResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )
        try:
            wa_id, flow_id = decrypt_flow_token(encrypted_flow_token)
        except Exception as e:
            self.logger.error(f"Error decrypting flow token: {e}")
            return JSONResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )

        user_data = await get_user_data(wa_id)
        if not user_data:
            self.logger.error(f"User data not found for wa_id {wa_id}")
            return JSONResponse(
                content={"error_msg": "User data not found"}, status_code=422
            )

        response_payload = {
            "screen": "subject_class_info",
            "data": {
                "subject_name": user_data.get("subject_name", ""),
                "class_name": user_data.get("class_name", ""),
            },
        }
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_personal_and_school_info_flow_data_exchange_action(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.info(
            "Handling data exchange action, with data: %s", decrypted_payload
        )

        data = decrypted_payload.get("data", {})
        full_name = data.get("personal_info_full_name")
        birthday = data.get("personal_info_birthday")
        location = data.get("personal_info_location")
        school_name = data.get("school_info_personal_birthday")
        school_location = data.get("school_info_school_location")

        encrypted_flow_token = decrypted_payload.get("flow_token")
        if not encrypted_flow_token:
            self.logger.error("Missing flow token")
            return JSONResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )
        try:
            wa_id, flow_id = decrypt_flow_token(encrypted_flow_token)
            self.logger.info(f"Decrypted flow token: {wa_id}, {flow_id}")
        except Exception as e:
            self.logger.error(f"Error decrypting flow token: {e}")
            return JSONResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )

        user_data = await get_user_data(wa_id)
        if not user_data:
            self.logger.error(f"User data not found for wa_id {wa_id}")
            return JSONResponse(
                content={"error_msg": "User data not found"}, status_code=422
            )

        user_data["name"] = full_name
        user_data["birthday"] = birthday
        user_data["location"] = location
        user_data["school_name"] = school_name
        user_data["school_location"] = school_location
        user_data["on_boarding_state"] = "personal_info_submitted"

        await update_user(
            wa_id,
            name=full_name,
            birthday=birthday,
            location=location,
            school_name=school_name,
            school_location=school_location,
            on_boarding_state="personal_info_submitted",
        )

        response_payload = {
            "screen": "SUCCESS",
            "data": {
                "extension_message_response": {
                    "params": {
                        "flow_token": encrypted_flow_token,
                    },
                },
            },
        }
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_subject_class_info_data_exchange_action(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.info("Handling subject class info data exchange action")

        data = decrypted_payload.get("data", {})
        subject_name = data.get("subject_name")
        class_name = data.get("class_name")

        encrypted_flow_token = decrypted_payload.get("flow_token")
        if not encrypted_flow_token:
            self.logger.error("Missing flow token")
            return JSONResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )
        try:
            wa_id, flow_id = decrypt_flow_token(encrypted_flow_token)
            self.logger.info(f"Decrypted flow token: {wa_id}, {flow_id}")
        except Exception as e:
            self.logger.error(f"Error decrypting flow token: {e}")
            return JSONResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )

        user_data = await get_user_data(wa_id)
        if not user_data:
            self.logger.error(f"User data not found for wa_id {wa_id}")
            return JSONResponse(
                content={"error_msg": "User data not found"}, status_code=422
            )

        user_data["subject_name"] = subject_name
        user_data["class_name"] = class_name
        user_data["on_boarding_state"] = "subject_class_info_submitted"

        await update_user(
            wa_id,
            subject_name=subject_name,
            class_name=class_name,
            on_boarding_state="subject_class_info_submitted",
        )

        response_payload = {
            "screen": "SUCCESS",
            "data": {
                "extension_message_response": {
                    "params": {
                        "flow_token": encrypted_flow_token,
                    },
                },
            },
        }
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_health_check(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.info("Received flow health check event ❤️‍🩹")
        response_payload = {"data": {"status": "active"}}
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def encrypt_flow_token(self, wa_id: str, flow_id: str) -> JSONResponse:
        encrypted_flow_token = encrypt_flow_token(wa_id, flow_id)
        return JSONResponse(content={"flow_token": encrypted_flow_token})

    async def process_response(
        self, response_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.info(f"Processing response: {response_payload}")

        try:
            response_bytes = json.dumps(response_payload).encode("utf-8")

            iv_bytes = base64.b64decode(initial_vector)
            inverted_iv_bytes = bytes(~b & 0xFF for b in iv_bytes)

            encryptor = Cipher(
                algorithms.AES(aes_key),
                modes.GCM(inverted_iv_bytes),
                backend=default_backend(),
            ).encryptor()
            encrypted_data = encryptor.update(response_bytes) + encryptor.finalize()
            encrypted_data_tag = encryptor.tag
            encrypted_data_bytes = encrypted_data + encrypted_data_tag

            encrypted_response = base64.b64encode(encrypted_data_bytes).decode("utf-8")
            self.logger.info(f"Encrypted response: {encrypted_response}")

            return PlainTextResponse(content=encrypted_response, status_code=200)
        except Exception as e:
            self.logger.error(f"Error encrypting response: {e}")
            return PlainTextResponse(content="Encryption failed", status_code=500)

    async def send_personal_and_school_info_flow(self, wa_id: str, name: str) -> None:
        flow_token = encrypt_flow_token(
            wa_id, settings.personal_and_school_info_flow_id
        )
        payload = {
            "messaging_product": "whatsapp",
            "to": wa_id,
            "recipient_type": "individual",
            "type": "interactive",
            "interactive": {
                "type": "flow",
                "header": {
                    "type": "text",
                    "text": "Start onboarding to Twiga 🦒",
                },
                "body": {
                    "text": "Welcome to Twiga! Let's get started with your onboarding process. ",
                },
                "footer": {
                    "text": "Please follow the the instructions.",
                },
                "action": {
                    "name": "flow",
                    "parameters": {
                        "flow_message_version": "3",
                        "flow_action": "navigate",
                        "flow_token": flow_token,
                        "flow_id": settings.personal_and_school_info_flow_id,
                        "flow_cta": "Start Onboarding",
                        "mode": "published",
                        "flow_action_payload": {
                            "screen": "personal_info",
                            "data": {"full_name": name},
                        },
                    },
                },
            },
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://graph.facebook.com/{settings.meta_api_version}/{settings.whatsapp_cloud_number_id}/messages",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.whatsapp_api_token.get_secret_value()}",
                },
                json=payload,
            )
            self.logger.info(
                f"WhatsApp API response: {response.status_code} - {response.text}"
            )


flow_client = FlowService()
