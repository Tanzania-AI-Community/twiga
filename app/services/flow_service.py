import logging
from fastapi.responses import PlainTextResponse, JSONResponse
from app.utils.flows_util import (
    decrypt_flow_webhook,
    encrypt_response,
    decrypt_flow_token,
    encrypt_flow_token,
)
from app.database.models import User
from app.database.db import get_user_data
from app.config import settings
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64
import json

logger = logging.getLogger(__name__)


class FlowService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        personal_and_school_info_flow_id = settings.personal_and_school_info_flow_id
        self.flow_token_handlers = {
            personal_and_school_info_flow_id: self.handle_personal_and_school_info_flow,
            # Add other flow tokens and their handlers here
        }

    async def handle_flow_webhook(self, body: dict) -> PlainTextResponse:
        # self.logger.debug(f"Received webhook payload: {body}")

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

        self.logger.info(
            f"Flow Webhook Decrypted payload: {decrypted_payload}"
        )  # TODO remove this line in production

        action = decrypted_payload.get("action")
        handler = self.get_action_handler(action)
        return await handler(decrypted_payload, aes_key, initial_vector)

    def get_action_handler(self, action: str):
        return {
            "ping": self.handle_health_check,
            "INIT": self.handle_init_action,
        }.get(action, self.handle_unknown_action)

    async def handle_unknown_action(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.warning(
            f"Unknown action received: {decrypted_payload.get('action')}"
        )
        response_payload = {"unknown": "event"}
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_init_action(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        # self.logger.info(
        #     "Handling Flow init action with data: %s",
        #     decrypted_payload,
        #     "aes_key: %s",
        #     aes_key,
        #     "initial_vector: %s",
        #     initial_vector,
        # )

        encrypted_flow_token = decrypted_payload.get("flow_token")
        if not encrypted_flow_token:
            self.logger.error("Missing flow token")
            return JSONResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )
        try:
            wa_id, flow_id = decrypt_flow_token(encrypted_flow_token)
            # self.logger.info(f"Decrypted flow token: {wa_id}, {flow_id}")
        except Exception as e:
            self.logger.error(f"Error decrypting flow token: {e}")
            return JSONResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )

        user_data = await get_user_data(wa_id)

        # self.logger.info(f"User data found: {user_data}")

        if not user_data:
            self.logger.error(f"User data not found for wa_id {wa_id}")
            return JSONResponse(
                content={"error_msg": "User data not found"}, status_code=422
            )

        # self.logger.info(f"Flow ID: {flow_id}")
        handler = self.flow_token_handlers.get(flow_id, self.handle_unknown_flow_token)

        return await handler(decrypted_payload, aes_key, initial_vector, user_data)

    async def handle_unknown_flow_token(
        self,
        decrypted_payload: dict,
        aes_key: bytes,
        initial_vector: str,
        user_data: dict,
    ) -> PlainTextResponse:
        self.logger.warning(f"Unknown flow token received")
        response_payload = {"error_msg": "Unknown flow token"}
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_personal_and_school_info_flow(
        self,
        decrypted_payload: dict,
        aes_key: bytes,
        initial_vector: str,
        user_data: dict,
    ) -> PlainTextResponse:
        self.logger.info("Handling personal and school info flow")

        response_payload = {
            "screen": "personal_info",
            "data": {"full_name": user_data.get("name", "Your Name")},
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
            # Encode response payload to byte array using UTF-8
            response_bytes = json.dumps(response_payload).encode("utf-8")

            # Prepare initialization vector by inverting all bits
            iv_bytes = base64.b64decode(initial_vector)
            inverted_iv_bytes = bytes(~b & 0xFF for b in iv_bytes)

            # Encrypt response byte array using AES-GCM
            encryptor = Cipher(
                algorithms.AES(aes_key),
                modes.GCM(inverted_iv_bytes),
                backend=default_backend(),
            ).encryptor()
            encrypted_data = encryptor.update(response_bytes) + encryptor.finalize()
            encrypted_data_tag = encryptor.tag
            encrypted_data_bytes = encrypted_data + encrypted_data_tag

            # Encode the whole output as base64 string
            encrypted_response = base64.b64encode(encrypted_data_bytes).decode("utf-8")
            self.logger.info(f"Encrypted response: {encrypted_response}")

            return PlainTextResponse(content=encrypted_response, status_code=200)
        except Exception as e:
            self.logger.error(f"Error encrypting response: {e}")
            return PlainTextResponse(content="Encryption failed", status_code=500)


flow_client = FlowService()
