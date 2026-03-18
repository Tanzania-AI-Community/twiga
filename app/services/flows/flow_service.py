import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import BackgroundTasks, Request
from fastapi.responses import JSONResponse, PlainTextResponse

import app.database.db as db
import app.database.enums as enums
import app.database.models as models
import app.utils.flow_utils as futil
import scripts.flows.designing_flows as flows_wip
from app.config import Environment, settings
from app.database.models import User
from app.services.flows.handlers.onboarding_flow_handler import OnboardingFlowHandler
from app.services.flows.handlers.subjects_classes_flow_handler import (
    SubjectsClassesFlowHandler,
)
from app.services.whatsapp_service import whatsapp_client
from app.utils.string_manager import StringCategory, strings


class FlowService:
    # Keep constants here for backward compatibility with tests/callers.
    _FLOW_SCREEN_SELECT_SUBJECT = SubjectsClassesFlowHandler._FLOW_SCREEN_SELECT_SUBJECT
    _FLOW_SCREEN_SELECT_CLASSES = SubjectsClassesFlowHandler._FLOW_SCREEN_SELECT_CLASSES
    _FLOW_SUBJECT_TITLE_MAX_LEN = SubjectsClassesFlowHandler._FLOW_SUBJECT_TITLE_MAX_LEN
    _FLOW_MAX_CHIPS_OPTIONS = SubjectsClassesFlowHandler._FLOW_MAX_CHIPS_OPTIONS
    _FLOW_MAX_SELECTED_SUBJECTS = SubjectsClassesFlowHandler._FLOW_MAX_SELECTED_SUBJECTS
    _FLOW_MAX_SELECTED_CLASSES = SubjectsClassesFlowHandler._FLOW_MAX_SELECTED_CLASSES
    _FLOW_ACTION_LOAD_SUBJECT_CLASSES = (
        SubjectsClassesFlowHandler._FLOW_ACTION_LOAD_SUBJECT_CLASSES
    )
    _FLOW_ACTION_SAVE_SUBJECT_CLASSES = (
        SubjectsClassesFlowHandler._FLOW_ACTION_SAVE_SUBJECT_CLASSES
    )
    _FLOW_ACTION_COMPLETE = SubjectsClassesFlowHandler._FLOW_ACTION_COMPLETE

    def __init__(self):
        self.logger = logging.getLogger(__name__)

        # Shared dependencies exposed for flow handlers.
        self.db = db
        self.enums = enums
        self.futil = futil
        self.settings = settings
        self.strings = strings
        self.whatsapp_client = whatsapp_client
        self.StringCategory = StringCategory

        # Flow-specific handlers.
        self._onboarding_flow_handler = OnboardingFlowHandler(service=self)
        self._subjects_classes_flow_handler = SubjectsClassesFlowHandler(service=self)

        self.data_exchange_action_handlers: Dict[str, Callable] = {}
        self.init_action_handlers: Dict[str, Callable] = {}

        # Register handlers only in app runtime environments.
        if settings.environment not in (
            Environment.PRODUCTION,
            Environment.STAGING,
            Environment.DEVELOPMENT,
        ):
            return

        # Check if flow IDs are set.
        assert settings.onboarding_flow_id and settings.onboarding_flow_id.strip()
        assert (
            settings.subjects_classes_flow_id
            and settings.subjects_classes_flow_id.strip()
        )

        self.data_exchange_action_handlers = {
            settings.onboarding_flow_id: self.handle_onboarding_data_exchange_action,
            settings.subjects_classes_flow_id: self.handle_subjects_classes_data_exchange_action,
        }

        # NOTE: only used when designing flows (work-in-progress).
        self.init_action_handlers = {
            settings.onboarding_flow_id: flows_wip.handle_onboarding_init_action,
            settings.subjects_classes_flow_id: flows_wip.handle_subjects_classes_init_action,
        }

    async def handle_flow_request(
        self, request: Request, bg_tasks: BackgroundTasks
    ) -> PlainTextResponse:
        try:
            body = await request.json()
            payload, aes_key, initial_vector = await self.futil.decrypt_flow_request(
                body
            )
            action = payload.get("action")
            flow_token = payload.get("flow_token")

            if action == "ping":
                return await self.handle_health_check(aes_key, initial_vector)

            if not flow_token:
                self.logger.error("Missing flow token")
                return PlainTextResponse(
                    content={
                        "error_msg": "Missing flow token, Unable to process request"
                    },
                    status_code=422,
                )

            # Get the user and flow ID.
            wa_id, flow_id = self.futil.decrypt_flow_token(flow_token)
            user = await self.db.get_user_by_waid(wa_id)

            if not user:
                self.logger.error(f"User not found for WA ID: {wa_id}")
                raise ValueError("User not found")

            if action == "data_exchange":
                handler = self.data_exchange_action_handlers.get(
                    flow_id, self.handle_unknown_flow
                )
                return await handler(user, payload, aes_key, initial_vector, bg_tasks)

            if action == "INIT":
                self.logger.warning(f"WIP Flow is being processed: {flow_id}")
                handler = self.init_action_handlers.get(flow_id)
                if handler is None:
                    return await self.handle_unknown_flow(
                        user, payload, aes_key, initial_vector
                    )
                response_payload = await handler(user)
                return await self.process_response(
                    response_payload, aes_key, initial_vector
                )

            return await self.handle_unknown_action(
                user, payload, aes_key, initial_vector
            )

        except ValueError as exc:
            self.logger.error(f"Error decrypting payload: {exc}")
            return PlainTextResponse(content="Decryption failed", status_code=421)
        except self.futil.FlowTokenError as exc:
            self.logger.error(f"Error decrypting flow token: {exc}")
            return PlainTextResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )
        except Exception as exc:
            self.logger.error(f"Unexpected error: {exc}")
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
            encrypted_response = self.futil.encrypt_response(
                response_payload, aes_key, initial_vector
            )
            return PlainTextResponse(content=encrypted_response, status_code=200)
        except Exception as exc:
            self.logger.error(f"Error encrypting response: {exc}")
            return PlainTextResponse(content="Encryption failed", status_code=500)

    async def handle_unknown_flow(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        **kwargs: Any,
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

    async def handle_onboarding_data_exchange_action(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse:
        return await self._onboarding_flow_handler.handle_data_exchange_action(
            user=user,
            payload=payload,
            aes_key=aes_key,
            initial_vector=initial_vector,
            background_tasks=background_tasks,
        )

    async def handle_subjects_classes_data_exchange_action(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse | JSONResponse:
        return await self._subjects_classes_flow_handler.handle_data_exchange_action(
            user=user,
            payload=payload,
            aes_key=aes_key,
            initial_vector=initial_vector,
            background_tasks=background_tasks,
        )

    # Compatibility wrappers for methods directly tested and/or reused.
    def _parse_subject_id(self, value: Any) -> int:
        return self._subjects_classes_flow_handler._parse_subject_id(value)

    def _parse_subject_ids(self, value: Any) -> List[int]:
        return self._subjects_classes_flow_handler._parse_subject_ids(value)

    def _parse_class_ids(self, value: Any) -> List[int]:
        return self._subjects_classes_flow_handler._parse_class_ids(value)

    def _get_subject_display_title(self, subject: models.Subject) -> str:
        return self._subjects_classes_flow_handler._get_subject_display_title(subject)

    def _get_subject_title_with_leading_emoji(self, subject: models.Subject) -> str:
        return (
            self._subjects_classes_flow_handler._get_subject_title_with_leading_emoji(
                subject
            )
        )

    def _truncate_flow_option_title(self, title: str) -> str:
        return self._subjects_classes_flow_handler._truncate_flow_option_title(title)

    def _is_active_class(self, class_: models.Class) -> bool:
        return self._subjects_classes_flow_handler._is_active_class(class_)

    def _build_subject_option(
        self, subject: models.Subject
    ) -> Optional[Dict[str, str]]:
        return self._subjects_classes_flow_handler._build_subject_option(subject)

    def _build_class_option_title(self, subject_title: str, grade_label: str) -> str:
        return self._subjects_classes_flow_handler._build_class_option_title(
            subject_title, grade_label
        )

    async def _build_subject_selection_screen_data(self, user: User) -> Dict[str, Any]:
        return await self._subjects_classes_flow_handler._build_subject_selection_screen_data(
            user
        )

    async def _build_subject_classes_screen_data(
        self, user: User, selected_subject_ids: List[int]
    ) -> Dict[str, Any]:
        return await self._subjects_classes_flow_handler._build_subject_classes_screen_data(
            user, selected_subject_ids
        )

    async def _save_multi_subject_class_selection(
        self, user: User, selected_subject_ids: List[int], selected_class_ids: List[int]
    ) -> User:
        return await self._subjects_classes_flow_handler._save_multi_subject_class_selection(
            user, selected_subject_ids, selected_class_ids
        )

    async def _save_subject_selection(
        self, user: User, subject_id: int, selected_class_ids: List[int]
    ) -> User:
        return await self._subjects_classes_flow_handler._save_subject_selection(
            user, subject_id, selected_class_ids
        )

    async def _refresh_user_by_wa_id(self, wa_id: str) -> User:
        return await self._subjects_classes_flow_handler._refresh_user_by_wa_id(wa_id)

    def _build_class_info_from_teacher_classes(
        self, teacher_classes: List[models.TeacherClass]
    ) -> Dict[str, List[str]]:
        return (
            self._subjects_classes_flow_handler._build_class_info_from_teacher_classes(
                teacher_classes
            )
        )

    async def _sync_user_class_info(self, user: User) -> User:
        return await self._subjects_classes_flow_handler._sync_user_class_info(user)

    async def _finalize_subject_configuration(self, user: User) -> User:
        return (
            await self._subjects_classes_flow_handler._finalize_subject_configuration(
                user
            )
        )

    async def update_user_classes(
        self, user: User, selected_classes_by_subject: Dict[str, List[int]]
    ) -> None:
        await self._subjects_classes_flow_handler.update_user_classes(
            user, selected_classes_by_subject
        )

    async def update_user_profile(
        self, user: User, data: dict, is_updating: bool
    ) -> None:
        await self._onboarding_flow_handler.update_user_profile(user, data, is_updating)

    async def send_user_settings_flow(self, user: User) -> None:
        await self._onboarding_flow_handler.send_user_settings_flow(user)

    async def send_personal_and_school_info_flow(self, user: User) -> None:
        await self._onboarding_flow_handler.send_personal_and_school_info_flow(user)

    async def send_subjects_classes_flow(self, user: User) -> None:
        await self._subjects_classes_flow_handler.send_subjects_classes_flow(user)

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

        await self.db.create_new_message_by_fields(
            user_id=user.id,
            role=self.enums.MessageRole.assistant,
            content=content,
            is_present_in_conversation=True,
        )


flow_client = FlowService()

# TODO - move this comment to a more appropriate location
# Note: in development mode call send_whatsapp_flow_message with mode="draft"
