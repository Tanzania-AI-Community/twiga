import logging
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse, PlainTextResponse

import app.database.models as models
from app.database.models import ClassInfo, User


class SubjectsClassesFlowHandler:
    """Flow-specific logic for the subjects/classes selection flow."""

    _FLOW_SCREEN_SELECT_SUBJECT = "select_subject"
    _FLOW_SCREEN_SELECT_CLASSES = "select_classes"
    _FLOW_SUBJECT_TITLE_MAX_LEN = 30
    _FLOW_MAX_CHIPS_OPTIONS = 20
    _FLOW_MAX_SELECTED_SUBJECTS = 3
    _FLOW_MAX_SELECTED_CLASSES = 10
    _FLOW_ACTION_LOAD_SUBJECT_CLASSES = "load_subject_classes"
    _FLOW_ACTION_SAVE_SUBJECT_CLASSES = "save_subject_classes"
    _FLOW_ACTION_COMPLETE = "complete_subject_configuration"

    def __init__(self, service: Any):
        self.service = service
        self.logger = logging.getLogger(__name__)

    async def handle_data_exchange_action(
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
                selected_subject_ids = self._parse_subject_ids(
                    data.get("selected_subject_ids", data.get("selected_subject_id"))
                )
                classes_data = await self.service._build_subject_classes_screen_data(
                    user=user, selected_subject_ids=selected_subject_ids
                )
                response_payload = self.service.futil.create_flow_response_payload(
                    screen=self._FLOW_SCREEN_SELECT_CLASSES, data=classes_data
                )
                return await self.service.process_response(
                    response_payload, aes_key, initial_vector
                )

            if component_action == self._FLOW_ACTION_SAVE_SUBJECT_CLASSES:
                subject_id = self._parse_subject_id(data.get("selected_subject_id"))
                selected_class_ids = self._parse_class_ids(
                    data.get("selected_class_ids")
                )
                refreshed_user = await self.service._save_subject_selection(
                    user=user,
                    subject_id=subject_id,
                    selected_class_ids=selected_class_ids,
                )
                subject_selection_data = (
                    await self.service._build_subject_selection_screen_data(
                        refreshed_user
                    )
                )
                response_payload = self.service.futil.create_flow_response_payload(
                    screen=self._FLOW_SCREEN_SELECT_SUBJECT, data=subject_selection_data
                )
                return await self.service.process_response(
                    response_payload, aes_key, initial_vector
                )

            if component_action == self._FLOW_ACTION_COMPLETE:
                selected_subject_ids = self._parse_subject_ids(
                    data.get("selected_subject_ids")
                )
                if not selected_subject_ids:
                    raise ValueError("No subject selected")

                selected_class_ids = self._parse_class_ids(
                    data.get("selected_class_ids")
                )
                if not selected_class_ids:
                    raise ValueError("No classes selected for selected subjects")

                await self._save_multi_subject_class_selection(
                    user=user,
                    selected_subject_ids=selected_subject_ids,
                    selected_class_ids=selected_class_ids,
                )

                was_onboarding_in_progress = (
                    user.onboarding_state
                    != self.service.enums.OnboardingState.completed
                )
                refreshed_user = await self._finalize_subject_configuration(user)
                encrypted_flow_token = payload.get("flow_token")
                response_payload = self.service.futil.create_flow_response_payload(
                    screen="SUCCESS", data={}, encrypted_flow_token=encrypted_flow_token
                )

                if (
                    was_onboarding_in_progress
                    and refreshed_user.onboarding_state
                    == self.service.enums.OnboardingState.completed
                ):
                    welcome_message = self.service.strings.get_string(
                        self.service.StringCategory.ONBOARDING, "welcome"
                    )
                    await self.service.whatsapp_client.send_message(
                        user.wa_id, welcome_message
                    )
                    await self.service._persist_visible_assistant_message(
                        user, welcome_message
                    )

                return await self.service.process_response(
                    response_payload, aes_key, initial_vector
                )

            return JSONResponse(
                content={"error_msg": "Unknown subjects/classes flow action"},
                status_code=422,
            )

        except ValueError as exc:
            return JSONResponse(content={"error_msg": str(exc)}, status_code=422)
        except Exception as exc:
            return JSONResponse(content={"error_msg": str(exc)}, status_code=500)

    async def _handle_legacy_subjects_classes_submission(
        self,
        user: User,
        payload: dict,
        data: Dict[str, Any],
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse | JSONResponse:
        subjects_with_classes = await self.service.db.read_subjects()

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

        welcome_message = self.service.strings.get_string(
            self.service.StringCategory.ONBOARDING, "welcome"
        )
        await self.service.whatsapp_client.send_message(user.wa_id, welcome_message)
        await self.service._persist_visible_assistant_message(user, welcome_message)

        encrypted_flow_token = payload.get("flow_token")
        response_payload = self.service.futil.create_flow_response_payload(
            screen="SUCCESS", data={}, encrypted_flow_token=encrypted_flow_token
        )
        return await self.service.process_response(
            response_payload, aes_key, initial_vector
        )

    def _parse_subject_id(self, value: Any) -> int:
        if isinstance(value, list):
            non_empty_values = [
                item for item in value if item is not None and str(item).strip() != ""
            ]
            if not non_empty_values:
                raise ValueError("No subject selected")
            value = non_empty_values[0]

        if value is None or str(value).strip() == "":
            raise ValueError("No subject selected")
        try:
            return int(str(value))
        except ValueError as exc:
            raise ValueError("Invalid subject selected") from exc

    def _parse_subject_ids(self, value: Any) -> List[int]:
        if value is None:
            return []

        values: List[Any]
        if isinstance(value, list):
            values = value
        else:
            values = [value]

        parsed_ids: List[int] = []
        for subject_id in values:
            if subject_id is None or str(subject_id).strip() == "":
                continue
            parsed_value = int(str(subject_id))
            if parsed_value not in parsed_ids:
                parsed_ids.append(parsed_value)

        if len(parsed_ids) > self._FLOW_MAX_SELECTED_SUBJECTS:
            raise ValueError(
                f"You can select up to {self._FLOW_MAX_SELECTED_SUBJECTS} subjects."
            )

        return parsed_ids

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
            parsed_value = int(str(class_id))
            if parsed_value not in parsed_ids:
                parsed_ids.append(parsed_value)

        if len(parsed_ids) > self._FLOW_MAX_SELECTED_CLASSES:
            raise ValueError(
                f"You can select up to {self._FLOW_MAX_SELECTED_CLASSES} classes."
            )
        return parsed_ids

    def _get_subject_display_title(self, subject: models.Subject) -> str:
        return subject.name.value.replace("_", " ").title()

    def _get_subject_title_with_leading_emoji(self, subject: models.Subject) -> str:
        display_value = subject.name.display_format
        parts = display_value.rsplit(" ", 1)
        if len(parts) == 2:
            name_part, emoji_part = parts
            if emoji_part:
                return f"{emoji_part} {name_part}"
        return display_value

    def _truncate_flow_option_title(self, title: str) -> str:
        if len(title) <= self._FLOW_SUBJECT_TITLE_MAX_LEN:
            return title
        return f"{title[: self._FLOW_SUBJECT_TITLE_MAX_LEN - 3]}..."

    def _is_active_class(self, class_: models.Class) -> bool:
        return class_.status == self.service.enums.SubjectClassStatus.active

    def _build_subject_option(
        self, subject: models.Subject
    ) -> Optional[Dict[str, str]]:
        if subject.id is None:
            return None
        subject_title = self._truncate_flow_option_title(
            self._get_subject_title_with_leading_emoji(subject)
        )
        return {"id": str(subject.id), "title": subject_title}

    def _build_class_option_title(self, subject_title: str, grade_label: str) -> str:
        full_title = f"{grade_label} - {subject_title}"
        if len(full_title) <= self._FLOW_SUBJECT_TITLE_MAX_LEN:
            return full_title

        prefix = f"{grade_label} - "
        available_subject_len = self._FLOW_SUBJECT_TITLE_MAX_LEN - len(prefix)
        if available_subject_len <= 3:
            return self._truncate_flow_option_title(full_title)

        truncated_subject = f"{subject_title[: available_subject_len - 3]}..."
        return f"{prefix}{truncated_subject}"

    async def _build_subject_selection_screen_data(self, user: User) -> Dict[str, Any]:
        subjects = await self.service.db.read_subjects() or []
        all_subject_options = [
            option
            for option in (self._build_subject_option(subject) for subject in subjects)
            if option is not None
        ]

        configured_subject_ids = {
            taught_class.class_.subject_id
            for taught_class in (user.taught_classes or [])
            if taught_class.class_ is not None
        }
        configured_subject_ids = {
            subject_id
            for subject_id in configured_subject_ids
            if subject_id is not None
        }
        configured_subject_id_strings = {
            str(subject_id) for subject_id in configured_subject_ids
        }

        configured_options = sorted(
            [
                option
                for option in all_subject_options
                if option["id"] in configured_subject_id_strings
            ],
            key=lambda option: option["title"].lower(),
        )
        configured_option_ids = {option["id"] for option in configured_options}
        remaining_options = sorted(
            [
                option
                for option in all_subject_options
                if option["id"] not in configured_option_ids
            ],
            key=lambda option: option["title"].lower(),
        )
        subject_options = (configured_options + remaining_options)[
            : self._FLOW_MAX_CHIPS_OPTIONS
        ]
        visible_subject_option_ids = {option["id"] for option in subject_options}
        selected_subject_ids = [
            str(subject_id)
            for subject_id in sorted(configured_subject_ids)
            if str(subject_id) in visible_subject_option_ids
        ][: self._FLOW_MAX_SELECTED_SUBJECTS]

        return {
            "subject_options": subject_options,
            "selected_subject_ids": selected_subject_ids,
            "has_subject_options": len(subject_options) > 0,
        }

    async def _build_subject_classes_screen_data(
        self, user: User, selected_subject_ids: List[int]
    ) -> Dict[str, Any]:
        if not selected_subject_ids:
            raise ValueError("No subject selected")

        subjects = await self.service.db.read_subjects() or []
        subject_lookup = {
            subject.id: subject for subject in subjects if subject.id is not None
        }
        valid_subject_ids = [
            subject_id
            for subject_id in selected_subject_ids
            if subject_id in subject_lookup
        ]

        if not valid_subject_ids:
            raise ValueError("Selected subject no longer exists")

        class_options: List[Dict[str, str]] = []
        for subject_id in valid_subject_ids:
            subject = subject_lookup[subject_id]
            subject_title = self._get_subject_display_title(subject)
            for class_ in subject.subject_classes or []:
                if class_.id is None or not self._is_active_class(class_):
                    continue
                class_options.append(
                    {
                        "id": str(class_.id),
                        "title": self._build_class_option_title(
                            subject_title=subject_title,
                            grade_label=class_.grade_level.display_format,
                        ),
                    }
                )

        class_options.sort(key=lambda option: option["title"].lower())
        class_options = class_options[: self._FLOW_MAX_CHIPS_OPTIONS]
        selected_subject_ids_set = set(valid_subject_ids)
        visible_class_ids = {option["id"] for option in class_options}
        selected_class_ids = sorted(
            {
                str(taught_class.class_id)
                for taught_class in (user.taught_classes or [])
                if taught_class.class_ is not None
                and taught_class.class_.subject_id in selected_subject_ids_set
                and str(taught_class.class_id) in visible_class_ids
            }
        )

        return {
            "selected_subject_ids": [
                str(subject_id) for subject_id in valid_subject_ids
            ],
            "has_classes": len(class_options) > 0,
            "classes_for_subject": class_options,
            "selected_class_ids": selected_class_ids,
            "no_classes_text": "No active classes are available for selected subjects.",
        }

    async def _save_multi_subject_class_selection(
        self, user: User, selected_subject_ids: List[int], selected_class_ids: List[int]
    ) -> User:
        if not selected_subject_ids:
            raise ValueError("No subject selected")

        subjects = await self.service.db.read_subjects() or []
        selected_subject_ids_set = set(selected_subject_ids)
        valid_class_ids = {
            class_.id
            for subject in subjects
            if subject.id in selected_subject_ids_set
            for class_ in (subject.subject_classes or [])
            if class_.id is not None and self._is_active_class(class_)
        }

        filtered_class_ids = [
            class_id for class_id in selected_class_ids if class_id in valid_class_ids
        ]
        if not filtered_class_ids:
            raise ValueError("No classes selected for selected subjects")

        await self.service.db.assign_teacher_to_classes(
            user=user, class_ids=filtered_class_ids
        )
        refreshed_user = await self._refresh_user_by_wa_id(user.wa_id)
        await self._sync_user_class_info(refreshed_user)
        return refreshed_user

    async def _save_subject_selection(
        self, user: User, subject_id: int, selected_class_ids: List[int]
    ) -> User:
        subject = await self.service.db.read_subject(subject_id)
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

        await self.service.db.assign_teacher_to_classes(
            user=user, class_ids=filtered_class_ids, subject_id=subject_id
        )
        refreshed_user = await self._refresh_user_by_wa_id(user.wa_id)
        await self._sync_user_class_info(refreshed_user)
        return refreshed_user

    async def _refresh_user_by_wa_id(self, wa_id: str) -> User:
        refreshed_user = await self.service.db.get_user_by_waid(wa_id)
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
        return await self.service.db.update_user(user)

    async def _finalize_subject_configuration(self, user: User) -> User:
        refreshed_user = await self._refresh_user_by_wa_id(user.wa_id)
        if not refreshed_user.taught_classes:
            raise ValueError("No classes selected for any subject")

        refreshed_user = await self._sync_user_class_info(refreshed_user)
        if (
            refreshed_user.onboarding_state
            != self.service.enums.OnboardingState.completed
        ):
            refreshed_user.state = self.service.enums.UserState.active
            refreshed_user.onboarding_state = (
                self.service.enums.OnboardingState.completed
            )
            refreshed_user = await self.service.db.update_user(refreshed_user)

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

            await self.service.db.assign_teacher_to_classes(user, all_class_ids)

            updated_subjects = {}
            for subject_key, class_ids in selected_classes_by_subject.items():
                subject_id = int(subject_key.replace("subject", ""))
                subject: Optional[models.Subject] = await self.service.db.read_subject(
                    subject_id
                )
                classes = await self.service.db.read_classes(class_ids)

                if not subject or not classes or len(classes) == 0:
                    raise ValueError("Subject or classes not found")

                updated_subjects[subject.name] = [cls.grade_level for cls in classes]

            # Update the user's class_info
            user.class_info = ClassInfo(classes=updated_subjects).model_dump()

            self.logger.debug(f"Updated user classes for subjects: {updated_subjects}")

            # Update the user state and onboarding state
            user.state = self.service.enums.UserState.active
            user.onboarding_state = self.service.enums.OnboardingState.completed
            await self.service.db.update_user(user)
        except Exception as exc:
            self.logger.error(f"Failed to update user classes for subjects: {str(exc)}")
            raise

    async def send_subjects_classes_flow(self, user: User) -> None:
        try:
            refreshed_user = await self.service._refresh_user_by_wa_id(user.wa_id)
            subject_selection_data = (
                await self.service._build_subject_selection_screen_data(refreshed_user)
            )
            response_payload = self.service.futil.create_flow_response_payload(
                screen=self._FLOW_SCREEN_SELECT_SUBJECT,
                data=subject_selection_data,
            )

            flow_strings = self.service.strings.get_category(
                self.service.StringCategory.FLOWS
            )
            # Check if the flow settings are set
            assert (
                self.service.settings.subjects_classes_flow_id
                and self.service.settings.subjects_classes_flow_id.strip()
            )

            # Send the flow
            await self.service.futil.send_whatsapp_flow_message(
                user=user,
                flow_id=self.service.settings.subjects_classes_flow_id,
                header_text=flow_strings["subjects_classes_flow_header"],
                body_text=flow_strings["subjects_classes_flow_body"],
                action_payload=response_payload,
                flow_cta=flow_strings["subjects_classes_flow_cta"],
            )
            await self.service._persist_flow_message(
                user=user,
                flow_id=self.service.settings.subjects_classes_flow_id,
                header_text=flow_strings["subjects_classes_flow_header"],
                body_text=flow_strings["subjects_classes_flow_body"],
            )
        except Exception as exc:
            self.logger.error(f"Error sending subjects classes flow: {exc}")
            raise
