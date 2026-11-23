import logging

from app.clients.whatsapp_client import whatsapp_client
from app.database import db
from app.database.enums import MessageRole, OnboardingState
from app.database.models import User
from app.services.flows.flow_service import flow_client
from app.utils.string_manager import StringCategory, strings

_MAX_NAME_LENGTH = 50
_UNSUPPORTED_MESSAGE_CONTENT = "warning: user sent an unsupported message type"


def usable_display_name(message_text: str) -> str | None:
    """Return a name that fits the user record, or None when the reply cannot be saved."""
    name = message_text.strip()
    if not name or len(name) > _MAX_NAME_LENGTH or name == _UNSUPPORTED_MESSAGE_CONTENT:
        return None
    return name


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
            if not await self._name_question_was_recorded(user):
                ask_name = strings.get_string(StringCategory.ONBOARDING, "ask_name")
                await self.send_recorded_message(user, ask_name)
                return

            name = usable_display_name(message_text)
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

    async def _name_question_was_recorded(self, user: User) -> bool:
        """True when the newest assistant message asked for the teacher's name."""
        if user.id is None:
            raise ValueError("User ID is unexpectedly None during onboarding.")

        latest_assistant_message = await db.get_latest_user_message_by_role(
            user.id, MessageRole.assistant
        )
        if latest_assistant_message is None:
            return False

        return latest_assistant_message.content in {
            strings.get_string(StringCategory.ONBOARDING, "ask_name"),
            strings.get_string(StringCategory.ONBOARDING, "ask_name_retry"),
        }

    async def _ask_again_for_name(self, user: User) -> None:
        retry_message = strings.get_string(StringCategory.ONBOARDING, "ask_name_retry")
        await self.send_recorded_message(user, retry_message)

    async def send_recorded_message(self, user: User, content: str) -> bool:
        """Send a message and record it only when WhatsApp accepts the send."""
        if user.id is None:
            raise ValueError("User ID is unexpectedly None during onboarding.")

        sent = await whatsapp_client.send_message(user.wa_id, content)
        if not sent:
            return False

        await db.create_new_message_by_fields(
            user_id=user.id,
            role=MessageRole.assistant,
            content=content,
            is_present_in_conversation=True,
        )
        return True

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
