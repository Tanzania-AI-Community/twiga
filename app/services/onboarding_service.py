import logging

from app.clients.whatsapp_client import whatsapp_client
from app.database import db
from app.database.enums import MessageRole, OnboardingState
from app.database.models import User
from app.services.flows.flow_service import flow_client
from app.utils.string_manager import StringCategory, strings

_MAX_NAME_LENGTH = 50
_UNSUPPORTED_MESSAGE_CONTENT = "warning: user sent an unsupported message type"


class OnboardingHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.flow_client = flow_client
        self.handlers = {
            OnboardingState.personal_info_submitted: self.handle_personal_info_submitted,
            OnboardingState.completed: self.handle_completed,
        }

    async def process_state(self, user: User, message_text: str):
        self.logger.debug(
            f"Onboarding user {user.wa_id} with onboarding_state {user.onboarding_state}"
        )
        assert user.onboarding_state is not None
        if user.onboarding_state == OnboardingState.new:
            await self.handle_new(user, message_text)
            return

        onboarding_handler = self.handlers.get(
            user.onboarding_state, self.handle_default
        )
        await onboarding_handler(user)
        # TODO: Update the user state and onboarding_state in the database (make sure its done somewhere)

    async def handle_new(self, user: User, message_text: str):
        try:
            name = self._usable_name(message_text)
            if name is None:
                await self._ask_again_for_name(user)
                return

            self.logger.debug(f"Saving name for user {user.wa_id}")
            user.name = name
            user.onboarding_state = OnboardingState.personal_info_submitted
            await db.update_user(user)
            await self.flow_client.send_subjects_classes_flow(user)
        except Exception as e:
            self.logger.error(f"Error handling new user {user.wa_id}: {str(e)}")

    def _usable_name(self, message_text: str) -> str | None:
        name = message_text.strip()
        if (
            not name
            or len(name) > _MAX_NAME_LENGTH
            or name == _UNSUPPORTED_MESSAGE_CONTENT
        ):
            return None
        return name

    async def _ask_again_for_name(self, user: User) -> None:
        if user.id is None:
            raise ValueError("User ID is unexpectedly None during onboarding.")

        retry_message = strings.get_string(StringCategory.ONBOARDING, "ask_name_retry")
        await whatsapp_client.send_message(user.wa_id, retry_message)
        await db.create_new_message_by_fields(
            user_id=user.id,
            role=MessageRole.assistant,
            content=retry_message,
            is_present_in_conversation=True,
        )

    async def handle_personal_info_submitted(self, user: User):
        try:
            self.logger.debug(
                f"Triggering send_subjects_classes_flow for user {user.wa_id}"
            )
            await self.flow_client.send_subjects_classes_flow(user)
        except Exception as e:
            self.logger.error(
                f"Error handling personal_info_submitted user {user.wa_id}: {str(e)}"
            )

    async def handle_completed(self, user: User):
        """Handle completed onboarding - keep user inactive until approved"""
        self.logger.debug(f"Completed onboarding for user {user.wa_id}.")

        # Send message that registration is pending approval
        if user.id is None:
            raise ValueError(
                "User ID is unexpectedly None during completed onboarding."
            )

        pending_message = strings.get_string(
            StringCategory.REGISTRATION, "pending_approval"
        )
        await whatsapp_client.send_message(user.wa_id, pending_message)
        await db.create_new_message_by_fields(
            user_id=user.id,
            role=MessageRole.assistant,
            content=pending_message,
            is_present_in_conversation=True,
        )

        # User remains in inactive state until admin approval

    async def handle_default(self, user: User):
        if user.id is None:
            raise ValueError("User ID is unexpectedly None during onboarding.")

        err_message = strings.get_string(StringCategory.ERROR, "general")
        await whatsapp_client.send_message(user.wa_id, err_message)
        await db.create_new_message_by_fields(
            user_id=user.id,
            role=MessageRole.assistant,
            content=err_message,
            is_present_in_conversation=True,
        )


onboarding_client = OnboardingHandler()
