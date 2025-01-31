from datetime import datetime
from typing import Dict, List, Optional, Callable
from dateutil.relativedelta import relativedelta
import logging
from fastapi import BackgroundTasks, Request
from fastapi.responses import PlainTextResponse, JSONResponse

import app.utils.flow_utils as futil
import app.database.db as db
from app.database.models import ClassInfo, User
from app.services.whatsapp_service import whatsapp_client
from app.config import settings, Environment
from app.utils.string_manager import StringCategory, strings
import app.database.enums as enums
import scripts.flows.designing_flows as flows_wip
import app.database.models as models


class FlowService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

        # Check if the business environment is set
        if settings.environment not in (
            Environment.PRODUCTION,
            Environment.STAGING,
            Environment.DEVELOPMENT,
        ):
            return
        # Check if the flow settings are set
        assert settings.onboarding_flow_id and settings.onboarding_flow_id.strip()
        assert (
            settings.subjects_classes_flow_id
            and settings.subjects_classes_flow_id.strip()
        )

        self.data_exchange_action_handlers: Dict[str, Callable] = {
            settings.onboarding_flow_id: self.handle_onboarding_data_exchange_action,
            settings.subjects_classes_flow_id: self.handle_subjects_classes_data_exchange_action,
        }

        # NOTE: This is only used when designing flows (i.e. work-in-progress)
        self.init_action_handlers: Dict[str, Callable] = {
            settings.onboarding_flow_id: flows_wip.handle_onboarding_init_action,
            settings.subjects_classes_flow_id: flows_wip.handle_subjects_classes_init_action,
        }

    async def handle_flow_request(
        self, request: Request, bg_tasks: BackgroundTasks
    ) -> PlainTextResponse:
        try:
            body = await request.json()
            payload, aes_key, initial_vector = await futil.decrypt_flow_request(body)
            action = payload.get("action")
            flow_token = payload.get("flow_token")

            if action == "ping":
                return await flow_client.handle_health_check(aes_key, initial_vector)

            if not flow_token:
                self.logger.error("Missing flow token")
                return PlainTextResponse(
                    content={
                        "error_msg": "Missing flow token, Unable to process request"
                    },
                    status_code=422,
                )

            # Get the user and flow ID
            wa_id, flow_id = futil.decrypt_flow_token(flow_token)
            user = await db.get_user_by_waid(wa_id)

            if not user:
                self.logger.error(f"User not found for WA ID: {wa_id}")
                raise ValueError("User not found")

            if action == "data_exchange":
                handler = flow_client.data_exchange_action_handlers.get(
                    flow_id, flow_client.handle_unknown_flow
                )
                return await handler(user, payload, aes_key, initial_vector, bg_tasks)
            elif action == "INIT":
                self.logger.warning(f"WIP Flow is being processed: {flow_id}")
                handler = flow_client.init_action_handlers.get(
                    flow_id, flow_client.handle_unknown_flow
                )
                response_payload = await handler(user)
                return await self.process_response(
                    response_payload, aes_key, initial_vector
                )
            else:
                return await flow_client.handle_unknown_action(
                    user, payload, aes_key, initial_vector
                )
        except ValueError as e:
            self.logger.error(f"Error decrypting payload: {e}")
            return PlainTextResponse(content="Decryption failed", status_code=421)
        except futil.FlowTokenError as e:
            self.logger.error(f"Error decrypting flow token: {e}")
            return PlainTextResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            return PlainTextResponse(content="Decryption failed", status_code=500)

    async def handle_health_check(
        self, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.debug("Received flow health check event ❤️‍🩹")
        response_payload = {"data": {"status": "active"}}
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def process_response(
        self, response_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.debug(
            f"Processing response: {response_payload} , AES Key: {aes_key} , IV: {initial_vector}"
        )
        try:
            encrypted_response = futil.encrypt_response(
                response_payload, aes_key, initial_vector
            )
            return PlainTextResponse(content=encrypted_response, status_code=200)
        except Exception as e:
            self.logger.error(f"Error encrypting response: {e}")
            return PlainTextResponse(content="Encryption failed", status_code=500)

    async def handle_unknown_flow(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        **kwargs,
    ) -> PlainTextResponse:
        self.logger.warning(f"Unknown flow received: {payload.get('flow_id')}")
        response_payload = {"unknown": "flow"}
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_unknown_action(
        self, user: User, payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.warning(f"Unknown action received: {payload.get('action')}")
        response_payload = {"unknown": "event"}
        return await self.process_response(response_payload, aes_key, initial_vector)

    """ *************** DATA EXCHANGE HANDLERS *************** """

    async def handle_onboarding_data_exchange_action(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse:
        try:
            self.logger.debug(f"Handling onboarding data exchange: {payload}")
            data = payload.get("data", {})
            is_update = data.get("is_updating", False)
            encrypted_flow_token = payload.get("flow_token")

            # Add a background task to update the user profile
            background_tasks.add_task(self.update_user_profile, user, data, is_update)

            response_payload = futil.create_flow_response_payload(
                screen="SUCCESS",
                data={},
                encrypted_flow_token=encrypted_flow_token,
            )
            return await self.process_response(
                response_payload, aes_key, initial_vector
            )
        except ValueError as e:
            return PlainTextResponse(content={"error_msg": str(e)}, status_code=422)
        except Exception as e:
            return PlainTextResponse(content={"error_msg": str(e)}, status_code=500)

    async def handle_subjects_classes_data_exchange_action(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse | JSONResponse:
        try:
            self.logger.info(f"Handling subjects and classes data exchange: {payload}")
            data = payload.get("data", {})

            self.logger.info(f"Handling subjects and classes data exchange: {data}")

            # Get subjects with their classes
            subjects_with_classes = await db.read_subjects()

            self.logger.info(f"Subjects with classes: {subjects_with_classes}")

            # Create a mapping of subject keys to subject IDs
            subject_key_to_id = {
                f"subject{i+1}": subject.id
                for i, subject in enumerate(subjects_with_classes or [])
            }

            # Extract selected classes for each subject
            selected_classes_by_subject = {
                str(subject_key_to_id[key.replace("selected_classes_for_", "")]): [
                    int(id) for id in value
                ]
                for key, value in data.items()
                if key.startswith("selected_classes_for_")
            }

            self.logger.info(
                f"Selected classes by subject: {selected_classes_by_subject}"
            )

            # Validate that at least one class is selected for any subject
            if not any(
                classes for classes in selected_classes_by_subject.values() if classes
            ):
                self.logger.error("No classes selected for any subject")
                return JSONResponse(
                    content={"error_msg": "No classes selected for any subject"},
                    status_code=422,
                )

            self.logger.info(
                f"Selected classes by subject: {selected_classes_by_subject}"
            )

            # Update user classes for each subject in the background
            background_tasks.add_task(
                self.update_user_classes,
                user,
                selected_classes_by_subject,
            )

            # Send a welcome message to the user
            await whatsapp_client.send_message(
                user.wa_id, strings.get_string(StringCategory.ONBOARDING, "welcome")
            )

            # Create the response payload
            encrypted_flow_token = payload.get("flow_token")
            response_payload = futil.create_flow_response_payload(
                screen="SUCCESS", data={}, encrypted_flow_token=encrypted_flow_token
            )
            return await self.process_response(
                response_payload, aes_key, initial_vector
            )

        except ValueError as e:
            return JSONResponse(content={"error_msg": str(e)}, status_code=422)
        except Exception as e:
            return PlainTextResponse(content={"error_msg": str(e)}, status_code=500)

    async def update_user_classes(
        self, user: User, selected_classes_by_subject: Dict[str, List[int]]
    ) -> None:
        try:
            # Ensure class_info is initialized
            if not user.class_info:
                user.class_info = ClassInfo(classes={}).model_dump()

            self.logger.debug(
                f"Updating user classes for subjects: {selected_classes_by_subject}"
            )

            all_class_ids = [
                class_id
                for class_ids in selected_classes_by_subject.values()
                for class_id in class_ids
            ]

            if not all_class_ids:
                raise ValueError("No classes selected for any subject")

            await db.assign_teacher_to_classes(user, all_class_ids)

            updated_subjects = {}
            for subject_key, class_ids in selected_classes_by_subject.items():
                subject_id = int(subject_key.replace("subject", ""))
                subject: Optional[models.Subject] = await db.read_subject(subject_id)
                classes = await db.read_classes(class_ids)

                if not subject or not classes or len(classes) == 0:
                    raise ValueError("Subject or classes not found")

                updated_subjects[subject.name] = [cls.grade_level for cls in classes]

            # Update the user's class_info
            user.class_info = ClassInfo(classes=updated_subjects).model_dump()

            self.logger.debug(f"Updated user classes for subjects: {updated_subjects}")

            # Update the user state and onboarding state
            user.state = enums.UserState.active
            user.onboarding_state = enums.OnboardingState.completed
            await db.update_user(user)
        except Exception as e:
            self.logger.error(f"Failed to update user classes for subjects: {str(e)}")
            raise

    """ *************** BACKGROUND TASKS *************** """

    async def update_user_profile(self, user: User, data: dict, is_updating: bool):
        try:
            # Get field values using prefix based on update status
            prefix = "update_" if is_updating else ""
            user.name = data.get(f"{prefix}full_name") or user.name
            user.birthday = (
                datetime.strptime(data[f"{prefix}birthday"], "%Y-%m-%d")
                if data.get(f"{prefix}birthday")
                else None if data.get(f"{prefix}birthday") else None
            )
            user.region = data.get(f"{prefix}region")
            user.school_name = data.get(f"{prefix}school_name")
            user.onboarding_state = enums.OnboardingState.personal_info_submitted

            # Update the database
            user = await db.update_user(user)

            # Send the select subjects flow if onboarding
            if not is_updating:
                await self.send_subjects_classes_flow(user)
        except Exception as e:
            await whatsapp_client.send_message(
                user.wa_id, strings.get_string(StringCategory.ERROR, "general")
            )
            self.logger.error(f"Failed to update onboarding data: {str(e)}")

    """ *************** FLOW SENDING METHODS *************** """

    # The same flow is sent for both settings and onboarding (onboarding_flow_id)
    async def send_user_settings_flow(self, user: User) -> None:
        flow_strings = strings.get_category(StringCategory.FLOWS)
        header_text = flow_strings["personal_settings_header"]
        body_text = flow_strings["personal_settings_body"]
        data = {
            "full_name": user.name or "Name",
            "min_date": "1900-01-01",
            "max_date": (datetime.now() - relativedelta(years=18)).strftime("%Y-%m-%d"),
            "is_updating": True,
            "region": user.region,
            "birthday": user.birthday.strftime("%Y-%m-%d") if user.birthday else None,
            "school_name": user.school_name,
        }
        # Check if the flow settings are set
        assert settings.onboarding_flow_id and settings.onboarding_flow_id.strip()

        await futil.send_whatsapp_flow_message(
            user=user,
            flow_id=settings.onboarding_flow_id,
            header_text=header_text,
            body_text=body_text,
            action_payload={
                "screen": "personal_info",
                "data": data,
            },
            flow_cta=flow_strings["personal_settings_cta"],
        )

    async def send_personal_and_school_info_flow(self, user: User) -> None:
        flow_strings = strings.get_category(StringCategory.FLOWS)
        header_text = flow_strings["start_onboarding_header"]
        body_text = flow_strings["start_onboarding_body"]
        data = {
            "full_name": user.name or "Name",
            "min_date": "1900-01-01",
            "max_date": (datetime.now() - relativedelta(years=18)).strftime("%Y-%m-%d"),
            "is_updating": False,
        }

        # Check if the flow settings are set
        assert settings.onboarding_flow_id and settings.onboarding_flow_id.strip()

        await futil.send_whatsapp_flow_message(
            user=user,
            flow_id=settings.onboarding_flow_id,
            header_text=header_text,
            body_text=body_text,
            action_payload={
                "screen": "personal_info",
                "data": data,
            },
            flow_cta=flow_strings["start_onboarding_cta"],
        )

    async def send_subjects_classes_flow(self, user: User) -> None:
        try:
            # Fetch available subjects with their classes from the database
            subjects = await db.read_subjects()
            self.logger.debug(f"Available subjects with classes: {subjects}")

            subjects_data = {}
            for i, subject in enumerate(subjects or [], start=1):
                subject_id = subject.id
                subject_title = subject.name.value
                classes = subject.subject_classes
                subjects_data[f"subject{i}"] = {
                    "subject_id": str(subject_id),
                    "subject_title": subject_title,
                    "classes": [
                        {"id": str(cls.id), "title": cls.grade_level.display_format}
                        for cls in classes or []
                    ],
                    "available": len(classes or []) > 0,
                    "label": f"Classes for {subject_title}",
                }
                subjects_data[f"subject{i}_available"] = len(classes or []) > 0
                subjects_data[f"subject{i}_label"] = f"Classes for {subject_title}"

            # Prepare the response payload
            response_payload = futil.create_flow_response_payload(
                screen="select_subjects_and_classes",
                data={
                    **subjects_data,
                    "select_subject_text": "Please select the subjects and the classes you teach.",
                    "no_subjects_text": "Sorry, there are no available subjects.",
                },
            )

            flow_strings = strings.get_category(StringCategory.FLOWS)
            # Check if the flow settings are set
            assert (
                settings.subjects_classes_flow_id
                and settings.subjects_classes_flow_id.strip()
            )

            # Send the flow
            await futil.send_whatsapp_flow_message(
                user=user,
                flow_id=settings.subjects_classes_flow_id,
                header_text=flow_strings["subjects_classes_flow_header"],
                body_text=flow_strings["subjects_classes_flow_body"],
                action_payload=response_payload,
                flow_cta=flow_strings["subjects_classes_flow_cta"],
            )
        except Exception as e:
            self.logger.error(f"Error sending subjects classes flow: {e}")
            raise


flow_client = FlowService()

# TODO -move this comment to a more appropriate location
# Note when in development mode call the send_whatsapp_flow_message method with mode="draft" to send a flow in draft mode
