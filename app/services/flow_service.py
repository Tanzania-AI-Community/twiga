from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
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
    _FLOW_SCREEN_SELECT_SUBJECT = "select_subject"
    _FLOW_SCREEN_SELECT_CLASSES = "select_classes"
    _FLOW_SUBJECT_TITLE_MAX_LEN = 30
    _FLOW_ACTION_LOAD_SUBJECT_CLASSES = "load_subject_classes"
    _FLOW_ACTION_SAVE_SUBJECT_CLASSES = "save_subject_classes"
    _FLOW_ACTION_COMPLETE = "complete_subject_configuration"

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
            self.logger.info(
                "Handling subjects/classes data exchange payload: %s", payload
            )
            data = payload.get("data", {})

            # Backward compatibility with the current deployed flow shape.
            if any(
                key.startswith("selected_classes_for_subject") for key in data.keys()
            ):
                return await self._handle_legacy_subjects_classes_submission(
                    user=user,
                    payload=payload,
                    data=data,
                    aes_key=aes_key,
                    initial_vector=initial_vector,
                    background_tasks=background_tasks,
                )

            component_action = data.get("component_action")
            if component_action == self._FLOW_ACTION_LOAD_SUBJECT_CLASSES:
                subject_id = self._parse_subject_id(data.get("selected_subject_id"))
                classes_data = await self._build_subject_classes_screen_data(
                    user=user, subject_id=subject_id
                )
                response_payload = futil.create_flow_response_payload(
                    screen=self._FLOW_SCREEN_SELECT_CLASSES, data=classes_data
                )
                return await self.process_response(
                    response_payload, aes_key, initial_vector
                )

            if component_action == self._FLOW_ACTION_SAVE_SUBJECT_CLASSES:
                subject_id = self._parse_subject_id(data.get("selected_subject_id"))
                selected_class_ids = self._parse_class_ids(
                    data.get("selected_class_ids")
                )
                refreshed_user = await self._save_subject_selection(
                    user=user,
                    subject_id=subject_id,
                    selected_class_ids=selected_class_ids,
                )
                subject_selection_data = (
                    await self._build_subject_selection_screen_data(refreshed_user)
                )
                response_payload = futil.create_flow_response_payload(
                    screen=self._FLOW_SCREEN_SELECT_SUBJECT, data=subject_selection_data
                )
                return await self.process_response(
                    response_payload, aes_key, initial_vector
                )

            if component_action == self._FLOW_ACTION_COMPLETE:
                was_onboarding_in_progress = (
                    user.onboarding_state != enums.OnboardingState.completed
                )
                refreshed_user = await self._finalize_subject_configuration(user)
                encrypted_flow_token = payload.get("flow_token")
                response_payload = futil.create_flow_response_payload(
                    screen="SUCCESS", data={}, encrypted_flow_token=encrypted_flow_token
                )

                if (
                    was_onboarding_in_progress
                    and refreshed_user.onboarding_state
                    == enums.OnboardingState.completed
                ):
                    welcome_message = strings.get_string(
                        StringCategory.ONBOARDING, "welcome"
                    )
                    await whatsapp_client.send_message(user.wa_id, welcome_message)
                    await self._persist_visible_assistant_message(user, welcome_message)

                return await self.process_response(
                    response_payload, aes_key, initial_vector
                )

            return JSONResponse(
                content={"error_msg": "Unknown subjects/classes flow action"},
                status_code=422,
            )

        except ValueError as e:
            return JSONResponse(content={"error_msg": str(e)}, status_code=422)
        except Exception as e:
            return PlainTextResponse(content={"error_msg": str(e)}, status_code=500)

    async def _handle_legacy_subjects_classes_submission(
        self,
        user: User,
        payload: dict,
        data: Dict[str, Any],
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse | JSONResponse:
        subjects_with_classes = await db.read_subjects()

        subject_key_to_id = {
            f"subject{i+1}": subject.id
            for i, subject in enumerate(subjects_with_classes or [])
            if subject.id is not None
        }

        selected_classes_by_subject = {
            str(subject_key_to_id[key.replace("selected_classes_for_", "")]): [
                int(class_id) for class_id in value
            ]
            for key, value in data.items()
            if key.startswith("selected_classes_for_")
            and subject_key_to_id.get(key.replace("selected_classes_for_", ""))
            is not None
        }

        if not any(class_ids for class_ids in selected_classes_by_subject.values()):
            return JSONResponse(
                content={"error_msg": "No classes selected for any subject"},
                status_code=422,
            )

        background_tasks.add_task(
            self.update_user_classes,
            user,
            selected_classes_by_subject,
        )

        welcome_message = strings.get_string(StringCategory.ONBOARDING, "welcome")
        await whatsapp_client.send_message(user.wa_id, welcome_message)
        await self._persist_visible_assistant_message(user, welcome_message)

        encrypted_flow_token = payload.get("flow_token")
        response_payload = futil.create_flow_response_payload(
            screen="SUCCESS", data={}, encrypted_flow_token=encrypted_flow_token
        )
        return await self.process_response(response_payload, aes_key, initial_vector)

    def _parse_subject_id(self, value: Any) -> int:
        if value is None or str(value).strip() == "":
            raise ValueError("No subject selected")
        try:
            return int(str(value))
        except ValueError as exc:
            raise ValueError("Invalid subject selected") from exc

    def _parse_class_ids(self, value: Any) -> List[int]:
        if value is None:
            return []

        values: List[Any]
        if isinstance(value, list):
            values = value
        else:
            values = [value]

        parsed_ids: List[int] = []
        for class_id in values:
            if class_id is None or str(class_id).strip() == "":
                continue
            parsed_ids.append(int(str(class_id)))
        return parsed_ids

    def _get_subject_display_title(self, subject: models.Subject) -> str:
        return subject.name.value.replace("_", " ").title()

    def _truncate_flow_option_title(self, title: str) -> str:
        if len(title) <= self._FLOW_SUBJECT_TITLE_MAX_LEN:
            return title
        return f"{title[: self._FLOW_SUBJECT_TITLE_MAX_LEN - 3]}..."

    def _is_active_class(self, class_: models.Class) -> bool:
        return class_.status == enums.SubjectClassStatus.active

    def _build_subject_option(
        self, subject: models.Subject
    ) -> Optional[Dict[str, str]]:
        if subject.id is None:
            return None
        subject_title = self._truncate_flow_option_title(
            self._get_subject_display_title(subject)
        )
        return {"id": str(subject.id), "title": subject_title}

    async def _build_subject_selection_screen_data(self, user: User) -> Dict[str, Any]:
        subjects = await db.read_subjects() or []
        subject_options = [
            option
            for option in (self._build_subject_option(subject) for subject in subjects)
            if option is not None
        ]

        configured_subject_ids = {
            taught_class.class_.subject_id
            for taught_class in (user.taught_classes or [])
            if taught_class.class_ is not None
        }

        return {
            "subject_options": subject_options,
            "has_subject_options": len(subject_options) > 0,
            "select_subject_text": "Select a subject, save its classes, then repeat for other subjects.",
            "configured_subjects_text": f"Configured subjects: {len(configured_subject_ids)}",
            "no_subjects_text": "Sorry, there are no available subjects.",
            "subject_dropdown_label": "Subject",
            "complete_button_label": "Complete",
        }

    async def _build_subject_classes_screen_data(
        self, user: User, subject_id: int
    ) -> Dict[str, Any]:
        subject = await db.read_subject(subject_id)
        if subject is None:
            raise ValueError("Selected subject no longer exists")

        classes = [
            class_
            for class_ in (subject.subject_classes or [])
            if class_.id is not None and self._is_active_class(class_)
        ]
        class_options = [
            {"id": str(class_.id), "title": class_.grade_level.display_format}
            for class_ in classes
            if class_.id is not None
        ]

        selected_class_ids = [
            str(taught_class.class_id)
            for taught_class in (user.taught_classes or [])
            if taught_class.class_ is not None
            and taught_class.class_.subject_id == subject_id
        ]

        subject_title = self._get_subject_display_title(subject)
        return {
            "selected_subject_id": str(subject_id),
            "selected_subject_label": subject_title,
            "has_classes": len(class_options) > 0,
            "classes_for_subject": class_options,
            "selected_classes_for_subject": selected_class_ids,
            "classes_label": "Select classes",
            "save_button_label": "Save Subject",
            "no_classes_text": f"No active classes are available for {subject_title}.",
        }

    async def _save_subject_selection(
        self, user: User, subject_id: int, selected_class_ids: List[int]
    ) -> User:
        subject = await db.read_subject(subject_id)
        if subject is None:
            raise ValueError("Selected subject no longer exists")

        valid_class_ids = {
            class_.id
            for class_ in (subject.subject_classes or [])
            if class_.id is not None and self._is_active_class(class_)
        }
        filtered_class_ids = [
            class_id for class_id in selected_class_ids if class_id in valid_class_ids
        ]

        await db.assign_teacher_to_classes(
            user=user, class_ids=filtered_class_ids, subject_id=subject_id
        )
        refreshed_user = await self._refresh_user_by_wa_id(user.wa_id)
        await self._sync_user_class_info(refreshed_user)
        return refreshed_user

    async def _refresh_user_by_wa_id(self, wa_id: str) -> User:
        refreshed_user = await db.get_user_by_waid(wa_id)
        if not refreshed_user:
            raise ValueError("User not found")
        return refreshed_user

    def _build_class_info_from_teacher_classes(
        self, teacher_classes: List[models.TeacherClass]
    ) -> Dict[str, List[str]]:
        class_info: Dict[str, set[str]] = {}
        for teacher_class in teacher_classes:
            class_obj = teacher_class.class_
            if class_obj is None:
                continue

            subject_key = class_obj.subject_.name.value
            grade_key = class_obj.grade_level.value
            class_info.setdefault(subject_key, set()).add(grade_key)

        return {
            subject: sorted(list(grade_levels))
            for subject, grade_levels in class_info.items()
        }

    async def _sync_user_class_info(self, user: User) -> User:
        class_info = self._build_class_info_from_teacher_classes(
            user.taught_classes or []
        )
        user.class_info = ClassInfo(classes=class_info).model_dump()
        return await db.update_user(user)

    async def _finalize_subject_configuration(self, user: User) -> User:
        refreshed_user = await self._refresh_user_by_wa_id(user.wa_id)
        if not refreshed_user.taught_classes:
            raise ValueError("No classes selected for any subject")

        refreshed_user = await self._sync_user_class_info(refreshed_user)
        if refreshed_user.onboarding_state != enums.OnboardingState.completed:
            refreshed_user.state = enums.UserState.active
            refreshed_user.onboarding_state = enums.OnboardingState.completed
            refreshed_user = await db.update_user(refreshed_user)

        return refreshed_user

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
            err_message = strings.get_string(StringCategory.ERROR, "general")
            await whatsapp_client.send_message(user.wa_id, err_message)
            await self._persist_visible_assistant_message(user, err_message)
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
        await self._persist_flow_message(
            user=user,
            flow_id=settings.onboarding_flow_id,
            header_text=header_text,
            body_text=body_text,
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
        await self._persist_flow_message(
            user=user,
            flow_id=settings.onboarding_flow_id,
            header_text=header_text,
            body_text=body_text,
        )

    async def send_subjects_classes_flow(self, user: User) -> None:
        try:
            refreshed_user = await self._refresh_user_by_wa_id(user.wa_id)
            subject_selection_data = await self._build_subject_selection_screen_data(
                refreshed_user
            )
            response_payload = futil.create_flow_response_payload(
                screen=self._FLOW_SCREEN_SELECT_SUBJECT,
                data=subject_selection_data,
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
            await self._persist_flow_message(
                user=user,
                flow_id=settings.subjects_classes_flow_id,
                header_text=flow_strings["subjects_classes_flow_header"],
                body_text=flow_strings["subjects_classes_flow_body"],
            )
        except Exception as e:
            self.logger.error(f"Error sending subjects classes flow: {e}")
            raise

    async def _persist_flow_message(
        self, user: User, flow_id: str, header_text: str, body_text: str
    ) -> None:
        flow_message = (
            f"[FLOW_SENT] id={flow_id} | header={header_text} | body={body_text}"
        )
        await self._persist_visible_assistant_message(user, flow_message)

    async def _persist_visible_assistant_message(
        self, user: User, content: str
    ) -> None:
        if user.id is None:
            self.logger.warning(
                "Skipping flow message persistence for user without ID."
            )
            return

        await db.create_new_message_by_fields(
            user_id=user.id,
            role=enums.MessageRole.assistant,
            content=content,
            is_present_in_conversation=True,
        )


flow_client = FlowService()

# TODO -move this comment to a more appropriate location
# Note when in development mode call the send_whatsapp_flow_message method with mode="draft" to send a flow in draft mode
