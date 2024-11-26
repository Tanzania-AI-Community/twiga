import logging

from app.database.models import User, OnboardingState
from app.services.flow_service import flow_client
from app.services.whatsapp_service import whatsapp_client
from app.utils.string_manager import strings, StringCategory


class OnboardingHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.flow_client = flow_client
        self.handlers = {
            OnboardingState.new: self.handle_new,
            OnboardingState.personal_info_submitted: self.handle_personal_info_submitted,
            OnboardingState.completed: self.handle_completed,
        }

    async def process_state(self, user: User):
        self.logger.debug(
            f"Onboarding user {user.wa_id} with onboarding_state {user.onboarding_state}"
        )
        onboarding_handler = self.handlers.get(
            user.onboarding_state, self.handle_default
        )
        await onboarding_handler(user)
        # TODO: Update the user state and onboarding_state in the database (make sure its done somewhere)

    async def handle_new(self, user: User):
        try:
            self.logger.debug(
                f"Triggering send_personal_and_school_info_flow for user {user.wa_id}"
            )
            await flow_client.send_personal_and_school_info_flow(user)
        except Exception as e:
            self.logger.error(f"Error handling new user {user.wa_id}: {str(e)}")

    async def handle_personal_info_submitted(self, user: User):
        try:
            await self.flow_client.send_select_subject_flow(user)
            self.logger.debug(
                f"Triggering send_select_subject_flow for user {user.wa_id}"
            )
        except Exception as e:
            self.logger.error(
                f"Error handling personal_info_submitted user {user.wa_id}: {str(e)}"
            )

    def handle_completed(self, user: User):
        self.logger.debug(f"Completed onboarding for user {user.wa_id}.")
        # TODO: Send a welcome message as the first message in the chatbot thread

    def handle_default(self, user: User):
        whatsapp_client.send_message(
            user.wa_id, strings.get_string(StringCategory.ERROR, "general")
        )


onboarding_client = OnboardingHandler()
