import logging
from fastapi.responses import PlainTextResponse
from app.utils.flows_util import decrypt_flow_webhook, encrypt_response
from app.database.models import User

logger = logging.getLogger(__name__)


class FlowService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def handle_health_check(self) -> PlainTextResponse:
        self.logger.info("Received flow health check event ❤️‍🩹")
        response_payload = {"data": {"status": "active"}}
        return self.encrypt_and_respond(response_payload)

    async def encrypt_and_respond(
        self, response_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        try:
            encrypted_response = encrypt_response(
                response_payload, aes_key, initial_vector
            )
            return PlainTextResponse(content=encrypted_response, status_code=200)
        except Exception as e:
            self.logger.error(f"Error encrypting response: {e}")
            return PlainTextResponse(content="Encryption failed", status_code=500)

    async def handle_flow_webhook(self, body: dict) -> PlainTextResponse:
        self.logger.debug(f"Received webhook payload: {body}")

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
        )  # TODO remove this line after testing

        if decrypted_payload.get("action") == "ping":
            return await self.handle_health_check()

        response_payload = {"unknown": "event"}
        return await self.encrypt_and_respond(response_payload, aes_key, initial_vector)


flow_client = FlowService()
