from datetime import datetime
from dateutil.relativedelta import relativedelta
import logging
from fastapi.responses import PlainTextResponse, JSONResponse
from app.utils.flows_util import (
    decrypt_flow_webhook,
    decrypt_flow_token,
    encrypt_flow_token,
)
from app.database.db import (
    get_classes_for_subject,
    get_subject_and_classes,
    get_user_by_waid,
    update_user,
    get_available_subjects,
)
from app.database.models import User
from app.services.whatsapp_service import whatsapp_client
from app.utils.whatsapp_utils import generate_payload
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
            self.logger.info(f"Decrypted data: {decrypted_data}")
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
        if flow_id == settings.onboarding_flow_id:
            return {
                "ping": self.handle_health_check,
                "INIT": self.handle_onboarding_init_action,
                "data_exchange": self.handle_onboarding_data_exchange_action,
            }.get(action, self.handle_unknown_action)

        if flow_id == settings.select_subjects_flow_id:
            return {
                "ping": self.handle_health_check,
                "INIT": self.handle_select_subjects_init_action,
                "data_exchange": self.handle_subject_data_exchange_action,
            }.get(action, self.handle_unknown_action)

        if flow_id == settings.select_classes_flow_id:
            return {
                "ping": self.handle_health_check,
                "INIT": self.handle_select_classes_init_action,
                "data_exchange": self.handle_classes_data_exchange_action,
            }.get(action, self.handle_unknown_action)

    async def handle_select_classes_init_action(
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

        # Get the subject title and classes for the given subject_id from the database
        subject_id = 1  # Hardcoded subject_id as 1, because init action is only used when testing
        subject_data = await get_subject_and_classes(subject_id)
        subject_title = subject_data["subject_name"]
        classes = subject_data["classes"]
        logger.debug(f"Subject title for subject ID {subject_id}: {subject_title}")
        logger.debug(f"Available classes for subject ID {subject_id}: {classes}")

        select_class_question_text = f"Select the class you are in for {subject_title}."
        select_class_text = f"This helps us find the best answers for your questions in {subject_title}."
        no_classes_text = (
            f"Sorry, currently there are no active classes for {subject_title}."
        )
        has_classes = len(classes) > 0

        response_payload = {
            "screen": "select_classes",
            "data": {
                "classes": (
                    classes
                    if has_classes
                    else [
                        {
                            "id": "0",
                            "title": "No classes available",
                        }
                    ]
                ),  # doing this because the response in whatsapp flows expects a list of classes with id, title, and grade_level
                "has_classes": has_classes,
                "no_classes_text": no_classes_text,
                "select_class_text": select_class_text,
                "select_class_question_text": select_class_question_text,
                "subject_id": str(subject_id),
            },
        }

        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_classes_data_exchange_action(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.info("Handling classes data exchange action", decrypted_payload)
        # log aes_key
        self.logger.info(f"AES Key: {aes_key}")

        data = decrypted_payload.get("data", {})
        self.logger.info("Data from payload : %s", data)
        selected_classes = data.get("selected_classes", [])
        subject_id = data.get("subject_id")  # Add this line to get the subject_id

        self.logger.info("Selected classes: %s", selected_classes)
        self.logger.info("Subject ID: %s", subject_id)  # Log the subject_id

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

        if not selected_classes:
            self.logger.error("No classes selected")
            return JSONResponse(
                content={"error_msg": "No classes selected"}, status_code=422
            )

        # not sure if this is right, need help to fix this
        # Update user's class_info
        class_info = user.class_info or {}
        # mark user as completed onboarding and state to active
        user.onboarding_state = "completed"
        user.state = "active"
        class_info[subject_id] = selected_classes
        user.class_info = class_info
        self.logger.info(f"User class info after update: {user.class_info}")
        # it will look like : User class info after update: {'1': ['1', '3']}

        await update_user(user)

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

    async def handle_unknown_action(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.warning(
            f"Unknown action received: {decrypted_payload.get('action')}"
        )
        response_payload = {"unknown": "event"}
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_onboarding_init_action(
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
            "data": {
                "full_name": user.name,
            },
        }

        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_select_subjects_init_action(
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

        # Get available subjects from the database
        subjects = await get_available_subjects()

        logger.debug(f"Available subjects: {subjects}")

        select_subject_text = "This helps us find the best answers for your questions."
        no_subjects_text = "Sorry, currently there are no active subjects."
        has_subjects = len(subjects) > 0
        response_payload = {
            "screen": "select_subjects",
            "data": {
                "subjects": (
                    subjects
                    if has_subjects
                    else [{"id": "0", "title": "No subjects available"}]
                ),  # doing this because the response in whatsapp flows expects a list of subjects with id and title
                "has_subjects": has_subjects,
                "no_subjects_text": no_subjects_text,
                "select_subject_text": select_subject_text,
            },
        }
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_onboarding_data_exchange_action(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.debug(
            "Handling data exchange action, with data: %s", decrypted_payload
        )

        data = decrypted_payload.get("data", {})
        is_updating = data.get("is_updating", False)
        logger.debug(f"Is updating: {is_updating}")

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

        full_name = (
            data.get("update_full_name") if is_updating else data.get("full_name")
        )
        birthday = data.get("update_birthday") if is_updating else data.get("birthday")
        region = data.get("update_region") if is_updating else data.get("region")
        school_name = (
            data.get("update_school_name") if is_updating else data.get("school_name")
        )

        user.name = full_name or user.name
        user.birthday = birthday
        user.region = region
        user.school_name = school_name
        user.onboarding_state = "personal_info_submitted"

        await update_user(user)
        # self.logger.info(f"User after update: {user}")

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

        response_text = "Thank you for submitting your information. Your onboarding is almost complete."
        options = None

        await whatsapp_client.send_message(user.wa_id, response_text, options)
        await self.send_select_subject_flow(user)

        # log response_payload
        self.logger.info(f"Final Response payload: {response_payload}")

        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_subject_data_exchange_action(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.info(
            "Handling subject class info data exchange action", decrypted_payload
        )
        # log aes_key
        self.logger.info(f"AES Key: {aes_key}")

        data = decrypted_payload.get("data", {})
        self.logger.info("Data from payload : %s", data)
        selected_subjects = data.get("selected_subjects", [])
        subject_id = data.get("subject_id")  # Add this line to get the subject_id

        self.logger.info("Selected subjects: %s", selected_subjects)
        self.logger.info("Subject ID: %s", subject_id)  # Log the subject_id

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

        if not selected_subjects:
            self.logger.error("No subjects selected")
            return JSONResponse(
                content={"error_msg": "No subjects selected"}, status_code=422
            )

        # Get the selected subject ids
        selected_subject_ids = [int(id_str) for id_str in selected_subjects]

        for subject_id in selected_subject_ids:
            self.logger.info(f"Subject id to get subjects for: {subject_id}")
            await self.send_select_classes_flow(user, subject_id)

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
        self, user: User, is_update: bool = False
    ) -> None:
        flow_token = encrypt_flow_token(user.wa_id, settings.onboarding_flow_id)
        header_text = (
            "Update your personal and school information 📝"
            if is_update
            else "Start onboarding to Twiga 🦒"
        )
        body_text = (
            "Let's update your personal and school information."
            if is_update
            else "Welcome to Twiga!, Looks like you are new here. Let's get started with your onboarding process."
        )

        logger.debug(f"Sending personal and school info flow to {user}")

        data = {
            "full_name": user.name if user.name else "User name",
            "min_date": "1900-01-01",
            "max_date": (datetime.now() - relativedelta(years=18)).strftime("%Y-%m-%d"),
            "is_updating": is_update,
        }

        if is_update:
            data.update(
                {
                    "region": user.region,
                    "birthday": user.birthday.strftime("%Y-%m-%d"),
                    "school_name": user.school_name,
                }
            )

        logger.debug(f"Screen Data for send_personal_and_school_info_flow: {data}")

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
                    "text": "Please follow the instructions.",
                },
                "action": {
                    "name": "flow",
                    "parameters": {
                        "flow_message_version": "3",
                        "flow_action": "navigate",
                        "flow_token": flow_token,
                        "flow_id": settings.onboarding_flow_id,
                        "flow_cta": (
                            "Update Information" if is_update else "Start Onboarding"
                        ),
                        "mode": "published",
                        "flow_action_payload": {
                            "screen": "personal_info",
                            "data": data,
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

    async def send_select_subject_flow(
        self, user: User, is_update: bool = False
    ) -> None:
        flow_token = encrypt_flow_token(user.wa_id, settings.select_subjects_flow_id)
        logger.debug(f"Sending select subject flow to {user}")

        # Get available subjects from the database
        subjects = await get_available_subjects()

        logger.debug(f"Available subjects: {subjects}")

        select_subject_text = "This helps us find the best answers for your questions."
        no_subjects_text = "Sorry, currently there are no active subjects."
        has_subjects = len(subjects) > 0

        header_text = (
            "Update your class and subject selection 📝"
            if is_update
            else "Start class and subject selection 📝"
        )
        body_text = (
            "Let's update your class and subject selection."
            if is_update
            else "Congratulations! You have completed the first step of onboarding. Let's proceed with selecting your classes and subjects."
        )

        response_payload = {
            "screen": "select_subjects",
            "data": {
                "subjects": (
                    subjects
                    if has_subjects
                    else [{"id": "0", "title": "No subjects available"}]
                ),  # doing this because the response in whatsapp flows expects a list of subjects with id and title
                "has_subjects": has_subjects,
                "no_subjects_text": no_subjects_text,
                "select_subject_text": select_subject_text,
            },
        }

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
                    "text": "Please follow the instructions.",
                },
                "action": {
                    "name": "flow",
                    "parameters": {
                        "flow_message_version": "3",
                        "flow_action": "navigate",
                        "flow_token": flow_token,
                        "flow_id": settings.select_subjects_flow_id,
                        "flow_cta": (
                            "Update subjects selection"
                            if is_update
                            else "Start subjects selection"
                        ),
                        "mode": "published",
                        "flow_action_payload": response_payload,
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

    async def send_update_select_subject_flow(self, user: User) -> JSONResponse:
        try:
            return await self.send_update_select_subject_flow(
                user.wa_id, user.name, is_update=True
            )

        except Exception as e:
            logger.error(f"Error updating select subject info: {e}")
            return JSONResponse(
                content={"status": "error", "message": "Internal server error"},
                status_code=500,
            )

    async def send_select_classes_flow(
        self, user: User, subject_id: int, is_update: bool = False
    ) -> None:
        flow_token = encrypt_flow_token(user.wa_id, settings.select_classes_flow_id)
        logger.debug(
            f"Sending select classes flow to {user} for subject ID {subject_id}"
        )

        # Get the subject title and classes for the given subject_id from the database
        subject_data = await get_subject_and_classes(subject_id)
        subject_title = subject_data["subject_name"]
        classes = subject_data["classes"]
        logger.debug(f"Subject title for subject ID {subject_id}: {subject_title}")
        logger.debug(f"Available classes for subject ID {subject_id}: {classes}")

        select_class_question_text = f"Select the class you are in for {subject_title}."
        select_class_text = f"This helps us find the best answers for your questions in {subject_title}."
        no_classes_text = (
            f"Sorry, currently there are no active classes for {subject_title}."
        )
        has_classes = len(classes) > 0

        header_text = (
            f"Update your class selection for {subject_title} 📝"
            if is_update
            else f"Start class selection for {subject_title} 📝"
        )
        body_text = (
            f"Let's select your class selection for {subject_title}."
            if is_update
            else f"Let's proceed with updating your classes for {subject_title}."
        )

        response_payload = {
            "screen": "select_classes",
            "data": {
                "classes": (
                    classes
                    if has_classes
                    else [
                        {
                            "id": "0",
                            "title": "No classes available",
                        }
                    ]
                ),  # doing this because the response in whatsapp flows expects a list of classes with id, title, and grade_level
                "has_classes": has_classes,
                "no_classes_text": no_classes_text,
                "select_class_text": select_class_text,
                "select_class_question_text": select_class_question_text,
                "subject_id": str(subject_id),  # Include the subject_id in the payload
            },
        }

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
                    "text": "Please follow the instructions.",
                },
                "action": {
                    "name": "flow",
                    "parameters": {
                        "flow_message_version": "3",
                        "flow_action": "navigate",
                        "flow_token": flow_token,
                        "flow_id": settings.select_classes_flow_id,
                        "flow_cta": (
                            "Update classes selection"
                            if is_update
                            else "Start classes selection"
                        ),
                        "mode": "published",
                        "flow_action_payload": response_payload,
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
