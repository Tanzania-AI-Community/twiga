from datetime import datetime
from typing import List
from dateutil.relativedelta import relativedelta
import logging
from fastapi import BackgroundTasks
from fastapi.responses import PlainTextResponse, JSONResponse
from app.utils.background_tasks_utils import add_background_task
from app.utils.flows_util import (
    create_flow_response_payload,
    decrypt_flow_webhook,
    decrypt_flow_token,
    encrypt_flow_token,
    handle_token_validation,
    send_whatsapp_flow_message,
    validate_user,
)
from app.database.db import (
    get_subject_and_classes,
    get_user_by_waid,
    update_user,
    get_available_subjects,
    update_user_selected_classes,
)
from app.database.models import User
from app.services.whatsapp_service import whatsapp_client
from app.config import settings
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64
import json

logger = logging.getLogger(__name__)


class FlowService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def handle_flow_webhook(
        self, body: dict, background_tasks: BackgroundTasks
    ) -> PlainTextResponse:
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
        # Check if the action is a data exchange action and handle accordingly
        if action in ["data_exchange", "INIT"]:
            if action == "data_exchange":
                return await handler(
                    decrypted_payload, aes_key, initial_vector, background_tasks
                )
            else:
                return await handler(decrypted_payload, aes_key, initial_vector)
        else:
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
        try:
            # Use helper functions for token and user validation
            encrypted_flow_token = decrypted_payload.get("flow_token")
            wa_id, flow_id = handle_token_validation(self.logger, encrypted_flow_token)
            user = await validate_user(self.logger, wa_id)

            subject_id = 1  # Hardcoded subject_id as 1, because init action is only used when testing
            subject_data = await get_subject_and_classes(subject_id)
            subject_title = subject_data["subject_name"]
            classes = subject_data["classes"]
            logger.debug(f"Subject title for subject ID {subject_id}: {subject_title}")
            logger.debug(f"Available classes for subject ID {subject_id}: {classes}")

            select_class_question_text = (
                f"Select the class you are in for {subject_title}."
            )
            select_class_text = f"This helps us find the best answers for your questions in {subject_title}."
            no_classes_text = (
                f"Sorry, currently there are no active classes for {subject_title}."
            )
            has_classes = len(classes) > 0

            response_payload = create_flow_response_payload(
                screen="select_classes",
                data={
                    "classes": (
                        classes
                        if has_classes
                        else [
                            {
                                "id": "0",
                                "title": "No classes available",
                            }
                        ]
                    ),
                    "has_classes": has_classes,
                    "no_classes_text": no_classes_text,
                    "select_class_text": select_class_text,
                    "select_class_question_text": select_class_question_text,
                    "subject_id": str(subject_id),
                },
            )

            return await self.process_response(
                response_payload, aes_key, initial_vector
            )

        except ValueError as e:
            return JSONResponse(
                content={"error_msg": str(e)},
                status_code=422,
            )

    async def handle_classes_data_exchange_action(
        self,
        decrypted_payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse:
        try:
            self.logger.info("Handling classes data exchange action", decrypted_payload)
            data = decrypted_payload.get("data", {})
            selected_classes = data.get("selected_classes", [])
            subject_id = data.get("subject_id")
            self.logger.info("Selected classes: %s", selected_classes)
            self.logger.info("Subject ID: %s", subject_id)

            # Use helper functions for token and user validation
            encrypted_flow_token = decrypted_payload.get("flow_token")
            wa_id, flow_id = handle_token_validation(self.logger, encrypted_flow_token)
            user = await validate_user(self.logger, wa_id)

            if not selected_classes:
                self.logger.error("No classes selected")
                return JSONResponse(
                    content={"error_msg": "No classes selected"}, status_code=422
                )

            # Convert selected classes to integers
            selected_classes_formatted = [
                int(class_id) for class_id in selected_classes
            ]

            # Send message to user
            responseText = "Thanks for submitting your class information, let me process that for you."
            await whatsapp_client.send_message(user.wa_id, responseText)

            # Add background task
            self.logger.info("Creating background task for classes data update")
            add_background_task(
                background_tasks,
                self.update_user_classes_data_background,
                user,
                selected_classes_formatted,
                int(subject_id),
            )

            response_payload = create_flow_response_payload(
                screen="SUCCESS", data={}, flow_token=encrypted_flow_token
            )
            return await self.process_response(
                response_payload, aes_key, initial_vector
            )

        except ValueError as e:
            return JSONResponse(content={"error_msg": str(e)}, status_code=422)

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
        try:
            # Use helper functions for token and user validation
            encrypted_flow_token = decrypted_payload.get("flow_token")
            wa_id, flow_id = handle_token_validation(self.logger, encrypted_flow_token)
            user = await validate_user(self.logger, wa_id)

            response_payload = create_flow_response_payload(
                screen="personal_info",
                data={
                    "full_name": user.name,
                },
            )

            return await self.process_response(
                response_payload, aes_key, initial_vector
            )

        except ValueError as e:
            return JSONResponse(content={"error_msg": str(e)}, status_code=422)

    async def handle_select_subjects_init_action(
        self, decrypted_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        try:
            # Use helper function for token validation
            encrypted_flow_token = decrypted_payload.get("flow_token")
            wa_id, flow_id = handle_token_validation(self.logger, encrypted_flow_token)

            # Get available subjects from the database
            subjects = await get_available_subjects()
            logger.debug(f"Available subjects: {subjects}")

            select_subject_text = (
                "This helps us find the best answers for your questions."
            )
            no_subjects_text = "Sorry, currently there are no active subjects."
            has_subjects = len(subjects) > 0

            response_payload = create_flow_response_payload(
                screen="select_subjects",
                data={
                    "subjects": (
                        subjects
                        if has_subjects
                        else [{"id": "0", "title": "No subjects available"}]
                    ),  # doing this because the response in whatsapp flows expects a list of subjects with id and title
                    "has_subjects": has_subjects,
                    "no_subjects_text": no_subjects_text,
                    "select_subject_text": select_subject_text,
                },
            )
            return await self.process_response(
                response_payload, aes_key, initial_vector
            )

        except ValueError as e:
            return JSONResponse(content={"error_msg": str(e)}, status_code=422)

    async def handle_onboarding_data_exchange_action(
        self,
        decrypted_payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse:
        try:
            self.logger.debug(
                "Handling data exchange action, with data: %s", decrypted_payload
            )
            data = decrypted_payload.get("data", {})
            is_updating = data.get("is_updating", False)
            logger.debug(f"Is updating: {is_updating}")

            # Use helper functions for token and user validation
            encrypted_flow_token = decrypted_payload.get("flow_token")
            wa_id, flow_id = handle_token_validation(self.logger, encrypted_flow_token)
            user = await validate_user(self.logger, wa_id)

            # Add the database update task to the background tasks
            self.logger.info(f"Creating background task for onboarding data update")
            add_background_task(
                background_tasks,
                self.update_onboarding_data_background,
                user,
                data,
                is_updating,
            )

            response_payload = create_flow_response_payload(
                screen="SUCCESS",
                data={},  # Empty data since SUCCESS screen handles its own structure
                flow_token=encrypted_flow_token,
            )
            return await self.process_response(
                response_payload, aes_key, initial_vector
            )

        except ValueError as e:
            return JSONResponse(content={"error_msg": str(e)}, status_code=422)

    async def handle_subject_data_exchange_action(
        self,
        decrypted_payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse:
        try:
            self.logger.info(
                "Handling subject class info data exchange action", decrypted_payload
            )
            data = decrypted_payload.get("data", {})
            # self.logger.info("Data from payload : %s", data)
            selected_subjects = data.get("selected_subjects", [])
            self.logger.info("Selected subjects: %s", selected_subjects)

            # Use helper functions for token and user validation
            encrypted_flow_token = decrypted_payload.get("flow_token")
            wa_id, flow_id = handle_token_validation(self.logger, encrypted_flow_token)
            user = await validate_user(self.logger, wa_id)

            if not selected_subjects:
                self.logger.error("No subjects selected")
                return JSONResponse(
                    content={"error_msg": "No subjects selected"}, status_code=422
                )

            # Add the database update task to the background tasks
            self.logger.info(f"Creating background task for subject data update")
            add_background_task(
                background_tasks,
                self.update_subject_data_background,
                user,
                selected_subjects,
            )

            self.logger.info(f"CREATED BACKGROUND TASK FOR SUBJECT DATA UPDATE")

            response_payload = create_flow_response_payload(
                screen="SUCCESS", data={}, flow_token=encrypted_flow_token
            )

            self.logger.info(
                f"SENDING RESPONSE PAYLOAD FOR SUBJECT DATA UPDATE: {response_payload}"
            )
            return await self.process_response(
                response_payload, aes_key, initial_vector
            )

        except ValueError as e:
            return JSONResponse(content={"error_msg": str(e)}, status_code=422)

    async def update_onboarding_data_background(
        self, user: User, data: dict, is_updating: bool
    ):
        try:
            full_name = (
                data.get("update_full_name") if is_updating else data.get("full_name")
            )
            birthday = (
                data.get("update_birthday") if is_updating else data.get("birthday")
            )
            region = data.get("update_region") if is_updating else data.get("region")
            school_name = (
                data.get("update_school_name")
                if is_updating
                else data.get("school_name")
            )
            user.name = full_name or user.name
            user.birthday = birthday
            user.region = region
            user.school_name = school_name
            user.onboarding_state = "personal_info_submitted"
            await update_user(user)
            self.logger.info(f"User after update: {user}")

            # send message to user saying that the personal info has been submitted
            responseText = "Thanks for submitting your personal information. Let's continue with your class and subject information so as to complete your onboarding."
            if is_updating:
                responseText = "Your personal information has been updated successfully. To update your settings again please type 'Settings'. How can I help you today?"

            await whatsapp_client.send_message(user.wa_id, responseText)

            # send select subject flow
            if not is_updating:
                await self.send_select_subject_flow(user)
        except Exception as e:
            responseText = "An error occurred during the onboarding process. Please try again later."
            await whatsapp_client.send_message(user.wa_id, responseText)
            self.logger.error(f"Failed to update onboarding data: {str(e)}")

    async def update_subject_data_background(
        self, user: User, selected_subjects: List[str], is_updating: bool = False
    ):
        try:
            selected_subject_ids = [int(id_str) for id_str in selected_subjects]

            # send message to user saying that the subject info has been submitted
            responseText = "Thanks for submitting your subject information. Let's continue with your class information for each subject."
            if (
                is_updating
            ):  # TODO update the flow to also send is_updating on payload so we can use it here to send a different message
                responseText = "Thank you for updating your subject information. Let's also update your class information for each subject."
            await whatsapp_client.send_message(user.wa_id, responseText)

            for subject_id in selected_subject_ids:
                await self.send_select_classes_flow(user, subject_id)
            self.logger.info(f"User after update: {user}")

        except Exception as e:
            responseText = "An error occurred during the onboarding process. Please try again later."
            await whatsapp_client.send_message(user.wa_id, responseText)
            self.logger.error(f"Failed to update subject data: {str(e)}")

    async def update_user_classes_data_background(
        self, user: User, selected_classes: List[int], subject_id: int
    ):
        try:
            # Update user classes in the database
            user = await update_user_selected_classes(
                user, selected_classes, subject_id
            )

            self.logger.info(
                f"FINAL User after update: {user}, Selected classes: {selected_classes}"
            )

            # send message to user saying that the class info has been submitted
            responseText = "Thanks for submitting your subject and classes information. How can I help you today?"
            await whatsapp_client.send_message(user.wa_id, responseText)

        except Exception as e:
            responseText = "An error occurred during the onboarding process. Please try again later."
            await whatsapp_client.send_message(user.wa_id, responseText)
            self.logger.error(f"Failed to update user subject classes: {str(e)}")

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
                    "is_updating": is_update,
                }
            )

        logger.debug(f"Screen Data for send_personal_and_school_info_flow: {data}")

        await send_whatsapp_flow_message(
            user=user,
            flow_id=settings.onboarding_flow_id,
            header_text=header_text,
            body_text=body_text,
            action_payload={
                "screen": "personal_info",
                "data": data,
            },
            flow_cta="Update Information" if is_update else "Start Onboarding",
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

        response_payload = create_flow_response_payload(
            screen="select_subjects",
            data={
                "subjects": (
                    subjects
                    if has_subjects
                    else [{"id": "0", "title": "No subjects available"}]
                ),  # doing this because the response in whatsapp flows expects a list of subjects with id and title
                "has_subjects": has_subjects,
                "no_subjects_text": no_subjects_text,
                "select_subject_text": select_subject_text,
            },
        )

        await send_whatsapp_flow_message(
            user=user,
            flow_id=settings.select_subjects_flow_id,
            header_text=header_text,
            body_text=body_text,
            action_payload=response_payload,
            flow_cta=(
                "Update subjects selection" if is_update else "Start subjects selection"
            ),
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

        response_payload = create_flow_response_payload(
            screen="select_classes",
            data={
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
        )

        await send_whatsapp_flow_message(
            user=user,
            flow_id=settings.select_classes_flow_id,
            header_text=header_text,
            body_text=body_text,
            action_payload=response_payload,
            flow_cta=(
                "Update classes selection" if is_update else "Start classes selection"
            ),
        )


flow_client = FlowService()
