from datetime import datetime
from typing import Dict, List, Optional
from dateutil.relativedelta import relativedelta
import logging
from fastapi import BackgroundTasks
from fastapi.responses import PlainTextResponse, JSONResponse

import app.utils.flow_utils as futil
import app.database.db as db
from app.database.models import ClassInfo, User
from app.services.whatsapp_service import whatsapp_client
from app.config import settings
from app.utils.string_manager import StringCategory, strings
import app.database.enums as enums
import scripts.flows.designing_flows as flows_wip
import app.database.models as models


class FlowService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.data_exchange_action_handlers: Dict[str, callable] = {
            settings.onboarding_flow_id: self.handle_onboarding_data_exchange_action,
            settings.select_subjects_flow_id: self.handle_subject_data_exchange_action,
            settings.select_classes_flow_id: self.handle_classes_data_exchange_action,
            settings.simple_subjects_classes_flow_id: self.handle_simple_subjects_classes_data_exchange_action,
        }

        # NOTE: This is only used when designing flows (i.e. work-in-progress)
        self.init_action_handlers: Dict[str, callable] = {
            settings.onboarding_flow_id: flows_wip.handle_onboarding_init_action,
            settings.select_subjects_flow_id: flows_wip.handle_select_subjects_init_action,
            settings.select_classes_flow_id: flows_wip.handle_select_classes_init_action,
            settings.simple_subjects_classes_flow_id: flows_wip.handle_simple_subjects_classes_init_action,
        }

    async def handle_flow_request(
        self, body: dict, bg_tasks: BackgroundTasks
    ) -> PlainTextResponse:
        try:
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

    async def handle_subject_data_exchange_action(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse:
        try:
            self.logger.info(f"Handling subject class info data exchange: {payload}")
            data = payload.get("data", {})
            selected_subject_ids = [int(id) for id in data.get("selected_subjects", [])]
            encrypted_flow_token = payload.get("flow_token")

            if not selected_subject_ids:
                self.logger.error("No subjects selected")
                raise ValueError("No subjects selected")

            # Send the select classes flow for each selected subject
            background_tasks.add_task(
                self.subject_background_task, user, selected_subject_ids
            )

            response_payload = futil.create_flow_response_payload(
                screen="SUCCESS", data={}, encrypted_flow_token=encrypted_flow_token
            )

            return await self.process_response(
                response_payload, aes_key, initial_vector
            )

        except ValueError as e:
            return PlainTextResponse(content={"error_msg": str(e)}, status_code=422)
        except Exception as e:
            return PlainTextResponse(content={"error_msg": str(e)}, status_code=500)

    async def handle_classes_data_exchange_action(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse:
        try:
            self.logger.info(f"Handling classes data exchange: {payload}")
            data = payload.get("data", {})
            selected_classes = [int(id) for id in data.get("selected_classes", [])]
            subject_id = int(data.get("subject_id"))  # This may raise an error
            encrypted_flow_token = payload.get("flow_token")

            if not selected_classes:
                self.logger.error("No classes selected")
                raise ValueError("No classes selected")

            background_tasks.add_task(
                self.update_user_classes,
                user,
                selected_classes,
                subject_id,
            )

            # Send a welcome message to the user
            # TODO: This is also not good due to the way we are handling flows right now, to be fixed.
            # TODO: This should not be sent when accessing the flow from the settings
            await whatsapp_client.send_message(
                user.wa_id, strings.get_string(StringCategory.ONBOARDING, "welcome")
            )

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

    async def handle_simple_subjects_classes_data_exchange_action(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse:
        try:
            self.logger.info(f"Handling subjects and classes data exchange: {payload}")
            data = payload.get("data", {})

            self.logger.info(f"Handling subjects and classes data exchange: {data}") 
    
            # Get subjects with their classes
            subjects_with_classes = await db.get_subjects_with_classes()

            self.logger.info(f"Subjects with classes: {subjects_with_classes}")
    
            # Create a mapping of subject keys to subject IDs
            subject_key_to_id = {
                f"subject{i+1}": subject["id"]
                for i, subject in enumerate(subjects_with_classes)
            }
    
            # Extract selected classes for each subject
            selected_classes_by_subject = {
                subject_key_to_id[key.replace("selected_classes_for_", "")]: [int(id) for id in value]
                for key, value in data.items()
                if key.startswith("selected_classes_for_")
            }

            self.logger.info(f"Selected classes by subject: {selected_classes_by_subject}")
    
            # Validate that at least one class is selected for any subject
            if not any(classes for classes in selected_classes_by_subject.values() if classes):
                self.logger.error("No classes selected for any subject")
                raise ValueError("No classes selected for any subject")
    
            self.logger.info(f"Selected classes by subject: {selected_classes_by_subject}")
    
            # Update user classes for each subject in the background
            background_tasks.add_task(
                db.update_user_classes_for_subjects,
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
    """ *************** BACKGROUND TASKS *************** """

    async def update_user_profile(self, user: User, data: dict, is_updating: bool):
        try:
            # Get field values using prefix based on update status
            prefix = "update_" if is_updating else ""
            user.name = data.get(f"{prefix}full_name") or user.name
            user.birthday = (
                datetime.strptime(data.get(f"{prefix}birthday"), "%Y-%m-%d")
                if data.get(f"{prefix}birthday")
                else None
            )
            user.region = data.get(f"{prefix}region")
            user.school_name = data.get(f"{prefix}school_name")
            user.onboarding_state = enums.OnboardingState.personal_info_submitted

            # Update the database
            await db.update_user(user)

            # Send the select subjects flow if onboarding
            if not is_updating:
                await self.send_select_subject_flow(user)
        except Exception as e:
            await whatsapp_client.send_message(
                user.wa_id, strings.get_string(StringCategory.ERROR, "general")
            )
            self.logger.error(f"Failed to update onboarding data: {str(e)}")

    async def subject_background_task(
        self, user: User, selected_subject_ids: List[int], is_updating: bool = False
    ):
        try:
            # NOTE: Instead of partially updating the users class_info, we send the select classes flows and update it that way
            # TODO: Replace this with a single flow being sent
            for subject_id in selected_subject_ids:
                await self.send_select_classes_flow(user, subject_id)
        except Exception as e:
            await whatsapp_client.send_message(
                user.wa_id, strings.get_string(StringCategory.ERROR, "general")
            )
            self.logger.error(f"Failed to update subject data: {str(e)}")

    async def update_user_classes(
        self, user: User, selected_classes: List[int], subject_id: int
    ):
        try:
            # TODO: This is done multiple times if the teacher selected multiple subjects - oof, must fix
            await db.assign_teacher_to_classes(user, selected_classes, subject_id)
            subject: Optional[models.Subject] = await db.read_subject(subject_id)
            classes = await db.read_classes(selected_classes)

            if not subject or not classes or len(classes) == 0:
                raise ValueError("Subject or classes not found")

            # Update the user so that the onboarding is complete
            user.state = enums.UserState.active
            user.onboarding_state = enums.OnboardingState.completed
            user.class_info = ClassInfo(
                subjects={
                    enums.SubjectName(subject.name): [
                        enums.GradeLevel(class_.grade_level) for class_ in classes
                    ]
                }
            ).model_dump()
            user = await db.update_user(user)

        except Exception as e:
            self.logger.error(f"Failed to update user subject classes: {str(e)}")

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

    # The same flow is sent for both settings and onboarding
    async def send_select_subject_flow(self, user: User) -> None:
        subjects = await db.get_available_subjects()
        formatted_subjects = [
            {
                "id": subject["id"],
                "title": enums.SubjectName(subject["title"]).title_format,
            }
            for subject in subjects
        ]

        flow_strings = strings.get_category(StringCategory.FLOWS)

        if len(formatted_subjects) == 0:
            await whatsapp_client.send_message(
                user.wa_id,
                strings.get_string(StringCategory.ERROR, "no_available_subjects"),
            )
            return

        header_text = flow_strings["subjects_flow_header"]
        body_text = flow_strings["subjects_flow_body"]

        # TODO: Leave this for now, discuss with Fredy if its necessary
        response_payload = futil.create_flow_response_payload(
            screen="select_subjects",
            data={
                "subjects": formatted_subjects,
                "has_subjects": True,
                "no_subjects_text": "",  # TODO: We don't need this
                "select_subject_text": flow_strings["select_subjects_text"],
            },
        )
        await futil.send_whatsapp_flow_message(
            user=user,
            flow_id=settings.select_subjects_flow_id,
            header_text=header_text,
            body_text=body_text,
            action_payload=response_payload,
            flow_cta=flow_strings["subjects_flow_cta"],
        )

    # The same flow is sent for both settings and onboarding
    async def send_select_classes_flow(
        self, user: User, subject_id: int, is_update: bool = False
    ) -> None:
        try:
            # Read the subject classes data from the database
            subject_data = await db.get_subject_grade_levels(subject_id)
            subject_title = enums.SubjectName(subject_data["subject_name"]).title_format
            classes = subject_data["classes"]

            flow_strings = strings.get_category(StringCategory.FLOWS)
            header_text = flow_strings["classes_flow_header"].format(
                subject=subject_title
            )
            body_text = flow_strings["classes_flow_body"]

            response_payload = futil.create_flow_response_payload(
                screen="select_classes",
                data=futil.create_subject_class_payload(
                    subject_title=subject_title,
                    classes=classes,
                    is_update=is_update,
                    subject_id=str(subject_id),
                ),
            )

            # Send the flow
            await futil.send_whatsapp_flow_message(
                user=user,
                flow_id=settings.select_classes_flow_id,
                header_text=header_text,
                body_text=body_text,
                action_payload=response_payload,
                flow_cta=flow_strings["classes_flow_cta"],
            )
        except Exception as e:
            self.logger.error(f"Error sending select classes flow: {e}")
            raise

    async def send_simple_subjects_classes_flow(self, user: User) -> None:
        try:
            # Fetch available subjects with their classes from the database
            subjects = await db.get_subjects_with_classes()
            self.logger.debug(f"Available subjects with classes: {subjects}")
            

            subjects_data = {}
            for i, subject in enumerate(subjects, start=1):
                subject_id = subject["id"]
                subject_title = subject["name"]
                classes = subject["classes"]
                subjects_data[f"subject{i}"] = {
                    "subject_id": str(subject_id),
                    "subject_title": subject_title,
                    "classes": [{"id": str(cls["id"]), "title": cls["title"]} for cls in classes],
                    "available": len(classes) > 0,
                    "label": f"Classes for {subject_title}",
                }
                subjects_data[f"subject{i}_available"] = len(classes) > 0
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

    
            # Send the flow
            await futil.send_whatsapp_flow_message(
                user=user,
                flow_id=settings.simple_subjects_classes_flow_id,
                header_text=flow_strings["simple_subjects_classes_flow_header"],
                body_text=flow_strings["simple_subjects_classes_flow_body"],
                action_payload=response_payload,
                flow_cta=flow_strings["simple_subjects_classes_flow_cta"],
                mode="draft",
            )
        except Exception as e:
            self.logger.error(f"Error sending simple subjects classes flow: {e}")
            raise

flow_client = FlowService()

# TODO -move this comment to a more appropriate location
# Note when in development mode call the send_whatsapp_flow_message method with mode="draft" to send a flow in draft mode