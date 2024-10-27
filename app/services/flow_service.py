import logging
import os
import requests
import json
import base64
from fastapi.responses import PlainTextResponse
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

from app.config import settings
from app.services.whatsapp_service import whatsapp_client
from app.utils.whatsapp_utils import generate_payload
from app.database.models import User

logger = logging.getLogger(__name__)


class FlowService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def decrypt_aes_key(self, encrypted_aes_key: str) -> bytes:
        private_key_pem = settings.whatsapp_business_private_key.get_secret_value()
        password = settings.whatsapp_business_private_key_password.get_secret_value()

        private_key = serialization.load_pem_private_key(
            private_key_pem.encode(),
            password=password.encode(),
            backend=default_backend(),
        )

        try:
            decrypted_key = private_key.decrypt(
                base64.b64decode(encrypted_aes_key),
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )
        except Exception as error:
            self.logger.error(f"Failed to decrypt the AES key: {error}")
            raise ValueError(
                "Failed to decrypt the request. Please verify your private key."
            )

        return decrypted_key

    def decrypt_payload(self, encrypted_data: str, aes_key: bytes, iv: str) -> dict:
        encrypted_data_bytes = base64.b64decode(encrypted_data)
        iv_bytes = base64.b64decode(iv)
        encrypted_data_body = encrypted_data_bytes[:-16]
        encrypted_data_tag = encrypted_data_bytes[-16:]
        decryptor = Cipher(
            algorithms.AES(aes_key),
            modes.GCM(iv_bytes, encrypted_data_tag),
            backend=default_backend(),
        ).decryptor()
        decrypted_data_bytes = (
            decryptor.update(encrypted_data_body) + decryptor.finalize()
        )
        return json.loads(decrypted_data_bytes.decode("utf-8"))

    def encrypt_response(self, response: dict, aes_key: bytes, iv: str) -> str:
        flipped_iv = bytearray()
        for byte in base64.b64decode(iv):
            flipped_iv.append(byte ^ 0xFF)

        encryptor = Cipher(
            algorithms.AES(aes_key),
            modes.GCM(bytes(flipped_iv)),
            backend=default_backend(),
        ).encryptor()

        encrypted_response = (
            encryptor.update(json.dumps(response).encode("utf-8"))
            + encryptor.finalize()
            + encryptor.tag
        )

        return base64.b64encode(encrypted_response).decode("utf-8")

    async def handle_flow_webhook(self, body: dict) -> PlainTextResponse:
        self.logger.debug(f"Received webhook payload: {body}")

        try:
            encrypted_flow_data = body["encrypted_flow_data"]
            encrypted_aes_key = body["encrypted_aes_key"]
            initial_vector = body["initial_vector"]

            aes_key = self.decrypt_aes_key(encrypted_aes_key)
            decrypted_payload = self.decrypt_payload(
                encrypted_flow_data, aes_key, initial_vector
            )
        except ValueError as e:
            self.logger.error(f"Error decrypting payload: {e}")
            return PlainTextResponse(content="Decryption failed", status_code=421)
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            return PlainTextResponse(content="Decryption failed", status_code=500)

        self.logger.info(
            f"Flow Webhook Decrypted payload: {decrypted_payload}"
        )  # TODO remove this line after testing

        if decrypted_payload.get("action") == "ping":
            self.logger.info("Received flow health check event ❤️‍🩹")
            response_payload = {"data": {"status": "active"}}
        else:
            response_payload = {"unknown": "event"}

        try:
            encrypted_response = self.encrypt_response(
                response_payload, aes_key, initial_vector
            )
            return PlainTextResponse(content=encrypted_response, status_code=200)
        except Exception as e:
            self.logger.error(f"Error encrypting response: {e}")
            return PlainTextResponse(content="Encryption failed", status_code=500)


flow_client = FlowService()
