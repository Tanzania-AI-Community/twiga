import logging
from fastapi.responses import PlainTextResponse, JSONResponse
from app.utils.flows_util import (
    decrypt_flow_webhook,
    decrypt_flow_token,
    encrypt_flow_token,
)
from app.database.db import get_user_by_waid, update_user
from app.database.models import User
from app.services.whatsapp_service import whatsapp_client
from app.utils.string_manager import strings, StringCategory
from app.utils.whatsapp_utils import generate_payload
from app.config import settings
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64
import json
import httpx

logger = logging.getLogger(__name__)

# Example config file for subjects and classes
SUBJECTS_CONFIG = {
    "Mathematics": ["Math 1", "Class 2", "Class 3"],
    "Geography": ["Class 1", "Geo 2", "Class 3"],
    "History": ["Class 1", "Class 2", "His 3"],
}


class FlowService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def handle_flow_webhook(self, body: dict) -> PlainTextResponse:
        try:
            decrypted_data = decrypt_flow_webhook(body)
            decrypted_payload = decrypted_data["decrypted_payload"]
            aes_key = decrypted_data["aes_key"]
            initial_vector = decrypted_data["initial_vector"]
            action = decrypted_payload.get("action")
        except ValueError as e:
            self.logger.error(f"Error decrypting payload: {e}")
            return PlainTextResponse(content="Decryption failed", status_code=421)
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            return PlainTextResponse(content="Decryption failed", status_code=500)

        self.logger.info(f"Flow Webhook Decrypted payload: {decrypted_payload}")

        if action == "ping":
            self.logger.info("Received ping action")
            return await self.handle_health_check(
                decrypted_payload, aes_key, initial_vector
            )

        flow_token = decrypted_payload.get("flow_token")
        if not flow_token:
            self.logger.error("Missing flow token")
            return JSONResponse(
                content={"error_msg": "Missing flow token, Unable to process request"},
                status_code=422,
            )

        try:
            wa_id, flow_id = decrypt_flow_token(flow_token)
            self.logger.info(f"Flow Action: {action}, Flow ID: {flow_id}")
        except Exception as e:
            self.logger.error(f"Error decrypting flow token: {e}")
            return JSONResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )

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

        user = await get_user_by_waid(wa_id)
        if not user:
            self.logger.error(f"User data not found for wa_id {wa_id}")
            return JSONResponse(
                content={"error_msg": "User data not found"}, status_code=422
            )

        response_payload = {
            "screen": "personal_info",
            "data": {"full_name": user.get("name", "Your Name")},
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

        # Get available subjects from the config
        subjects = [
            {"id": str(i + 1), "title": subject}
            for i, subject in enumerate(SUBJECTS_CONFIG.keys())
        ]

        response_payload = {
            "screen": "select_subject",
            "data": {
                "subjects": subjects,
                "selected_classes_text": "Please select a subject to proceed",
                "select_class_text": "Please select a class to proceed",
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
        school_name = data.get(
            "school_info_personal_birthday"
        )  # should be school_info_school_name, we need to update the published flow too
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

        user = await get_user_by_waid(wa_id)
        self.logger.info(f"User after get: {user}")
        if not user:
            self.logger.error(f"User data not found for wa_id {wa_id}")
            return JSONResponse(
                content={"error_msg": "User data not found"}, status_code=422
            )

        user.name = full_name if full_name else user.name
        user.birthday = birthday
        user.location = location
        user.school_name = school_name
        user.school_location = school_location
        user.onboarding_state = "personal_info_submitted"

        self.logger.info(f"Going to update user: {user}")
        await update_user(user)
        self.logger.info(f"User after update: {user}")

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

        response_text = strings.get_string(
            StringCategory.ONBOARDING, "personal_info_submitted"
        )
        options = None

        await whatsapp_client.send_message(user.wa_id, response_text, options)
        # send class and subject info flow
        await self.send_class_and_subject_info_flow(user.wa_id, user.name)

        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_subject_class_info_data_exchange_action(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.info(
            "Handling subject class info data exchange action", decrypted_payload
        )

        data = decrypted_payload.get("data", {})
        self.logger.info("Data from payload : %s", data)
        subject_id = data.get("subject_id")
        class_ids = data.get("class_ids", [])
        type = data.get("type")

        self.logger.info("Type is: , %s", type)

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

        user = await get_user_by_waid(wa_id)
        if not user:
            self.logger.error(f"User data not found for wa_id {wa_id}")
            return JSONResponse(
                content={"error_msg": "User data not found"}, status_code=422
            )

        classes = SUBJECTS_CONFIG[list(SUBJECTS_CONFIG.keys())[0]]

        classes_data = [
            {"id": str(i + 1), "title": cls} for i, cls in enumerate(classes)
        ]

        if type == "subject_selected":
            self.logger.info(f"Subject selected Action in exchange: {subject_id}")
            # make sure we have a valid subject id
            if not subject_id:
                self.logger.error("Missing subject id")
                # Get available subjects from the config
                subjects = [
                    {"id": str(i + 1), "title": subject}
                    for i, subject in enumerate(SUBJECTS_CONFIG.keys())
                ]
                response_payload = {
                    "screen": "select_subject",
                    "data": {
                        "subjects": subjects,
                        "selected_classes_text": "Please select a subject to proceed",
                        "select_class_text": "Please select a class to proceed",
                        "classes": classes_data,
                    },
                }

            # Get Subject Classes
            subject_name = list(SUBJECTS_CONFIG.keys())[int(subject_id) - 1]
            subject_classes = SUBJECTS_CONFIG[subject_name]

            # TODO Get the classes the user has selected for the subject (or for all subjects), then pass it to the
            # user_selected_classes = []
            # for now we will use the classes from the config
            user_selected_classes = subject_classes

            response_payload = {
                "screen": "select_subject",
                "subject_id": subject_id,
                "data": {
                    "data-" "selected_subject": subject_id,
                    "selected_subject_name": subject_name,
                    "selected_classes_text": f"Selected classes for {subject_name} are: {', '.join(user_selected_classes)}",
                    "classes": classes_data,
                },
            }
            return await self.process_response(
                response_payload, aes_key, initial_vector
            )

        if type == "selected_classes":
            self.logger.info(f"Class selected Action in exchange: {class_ids}")
            # make sure we have a valid class id
            if not class_ids:
                self.logger.error("Missing class id")
                return JSONResponse(
                    content={"error_msg": "Missing class id"}, status_code=422
                )

            # Get Subject Classes
            subject_name = list(SUBJECTS_CONFIG.keys())[int(subject_id) - 1]
            subject_classes = SUBJECTS_CONFIG[subject_name]

            # TODO Get the classes the user has selected for the subject (or for all subjects), then pass it to the
            # user_selected_classes = []
            # for now we will use the all classes from the config
            user_selected_classes = subject_classes

            response_payload = {
                "screen": "select_subject",
                "subject_id": subject_id,
                "data": {
                    "selected_subject": subject_id,
                    "selected_subject_name": subject_name,
                    "selected_classes_text": f"Selected classes for {subject_name} are: {', '.join(user_selected_classes)}",
                    "classes": classes_data,
                },
            }
            return await self.process_response(
                response_payload, aes_key, initial_vector
            )

        if type == "selecting_classes":
            # Get the subject name from the subject ID
            subject_name = list(SUBJECTS_CONFIG.keys())[int(subject_id) - 1]

            # Get the classes for the selected subject
            classes = SUBJECTS_CONFIG[subject_name]
            classes_data = [
                {"id": str(i + 1), "title": cls} for i, cls in enumerate(classes)
            ]

            response_payload = {
                "screen": "select_classes",
                "data": {
                    "classes": classes_data,
                    "selected_subject_name": subject_name,
                    "selected_subject": subject_id,
                    "selected_classes_info": f"Select the classes you teach for {subject_name} subject",
                },
            }
            return await self.process_response(
                response_payload, aes_key, initial_vector
            )

        if type == "completed":
            self.logger.info("Flow completed")
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

            user = User(wa_id=wa_id, onboarding_state="completed", state="active")

            await update_user(user)

            response_text = strings.get_template(
                StringCategory.ONBOARDING, "completed", user_name=user.name
            )
            options = None

            await whatsapp_client.send_message(user.wa_id, response_text, options)
            return await self.process_response(
                response_payload, aes_key, initial_vector
            )

        else:
            return JSONResponse(
                content={"status": "error", "message": "Invalid type provided"},
                status_code=400,
            )

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
        self.logger.info(
            f"Processing response: {response_payload} , AES Key: {aes_key} , IV: {initial_vector}"
        )

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

    async def send_personal_and_school_info_flow(
        self, wa_id: str, name: str, is_update: bool = False
    ) -> None:
        flow_token = encrypt_flow_token(
            wa_id, settings.personal_and_school_info_flow_id
        )
        header_text = (
            "Update your personal and school information 📝"
            if is_update
            else "Start onboarding to Twiga 🦒"
        )
        body_text = (
            "Let's update your personal and school information."
            if is_update
            else "Welcome to Twiga! Let's get started with your onboarding process."
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
                    "text": header_text,
                },
                "body": {
                    "text": body_text,
                },
                "footer": {
                    "text": "Please follow the instructions.",
                },
                "action": {
                    "name": "flow",
                    "parameters": {
                        "flow_message_version": "3",
                        "flow_action": "navigate",
                        "flow_token": flow_token,
                        "flow_id": settings.personal_and_school_info_flow_id,
                        "flow_cta": (
                            "Update Information" if is_update else "Start Onboarding"
                        ),
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

    async def send_class_and_subject_info_flow(self, wa_id: str, name: str) -> None:
        flow_token = encrypt_flow_token(wa_id, settings.subject_class_info_flow_id)

        # Get available subjects from the config
        subjects = [
            {"id": str(i + 1), "title": subject}
            for i, subject in enumerate(SUBJECTS_CONFIG.keys())
        ]

        payload = {
            "messaging_product": "whatsapp",
            "to": wa_id,
            "recipient_type": "individual",
            "type": "interactive",
            "interactive": {
                "type": "flow",
                "header": {
                    "type": "text",
                    "text": "Start class and subject selection 📝",
                },
                "body": {
                    "text": "Congratulations! You have completed the first step of onboarding. Let's proceed with selecting your classes and subjects.",
                },
                "footer": {
                    "text": "Please follow the instructions.",
                },
                "action": {
                    "name": "flow",
                    "parameters": {
                        "flow_message_version": "3",
                        "flow_action": "navigate",
                        "flow_token": flow_token,
                        "flow_id": settings.subject_class_info_flow_id,
                        "flow_cta": "Start Selection",
                        "mode": "published",
                        "flow_action_payload": {
                            "screen": "select_subject",
                            "data": {
                                "subjects": subjects,
                                "selected_classes_text": "Please select a subject to proceed",
                                "select_class_text": "Please select a class to proceed",
                            },
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

    async def send_update_personal_and_school_info_flow(
        self, user: User
    ) -> JSONResponse:
        try:
            return await self.send_personal_and_school_info_flow(
                user.wa_id, user.name, is_update=True
            )

        except Exception as e:
            logger.error(f"Error updating personal info: {e}")
            return JSONResponse(
                content={"status": "error", "message": "Internal server error"},
                status_code=500,
            )


flow_client = FlowService()
