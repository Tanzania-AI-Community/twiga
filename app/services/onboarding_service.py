import logging
from typing import List, Optional, Tuple

from app.database.models import User, OnboardingState, UserState
from app.services.flow_service import flow_client
from app.database.db import update_user


class OnboardingHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.flow_client = flow_client
        self.state_handlers = {
            OnboardingState.new: self.handle_new,
            OnboardingState.personal_info_submitted: self.handle_personal_info_submitted,
            OnboardingState.class_subject_info_submitted: self.handle_class_subject_info_submitted,
            OnboardingState.completed: self.handle_completed,
        }

    async def handle_new(self, user: User) -> Tuple[str, Optional[List[str]]]:
        try:
            # Call the send_personal_and_school_info_flow method from FlowService
            await self.flow_client.send_personal_and_school_info_flow(user.wa_id)

            self.logger.info(
                f"Triggered send_personal_and_school_info_flow for user {user.wa_id}"
            )

            response_text = None  # we don't want to send a response here since the flow will handle it
            options = None
            return response_text, options

        except Exception as e:
            self.logger.error(f"Error handling new user {user.wa_id}: {str(e)}")
            response_text = "An error occurred during the onboarding process. Please try again later."
            options = None
            return response_text, options

    def handle_personal_info_submitted(
        self, user: User
    ) -> Tuple[str, Optional[List[str]]]:
        response_text = "Thank you for submitting your personal information. Please provide your class and subject information."
        options = ["Submit Class & Subject Info"]
        return response_text, options

    def handle_class_subject_info_submitted(
        self, user: User
    ) -> Tuple[str, Optional[List[str]]]:
        response_text = "Thank you for submitting your class and subject information. Your onboarding is almost complete."
        options = ["Complete Onboarding"]
        return response_text, options

    def handle_completed(self, user: User) -> Tuple[str, Optional[List[str]]]:
        response_text = "Your onboarding is complete. Welcome!"
        options = None
        return response_text, options

    def handle_default(self, user: User) -> Tuple[str, Optional[List[str]]]:
        response_text = "I'm not sure how to handle your request."
        options = None
        return response_text, options

    async def process_state(self, user: User) -> Tuple[str, Optional[List[str]]]:
        # Get the user's current state from the user object
        user_state = user.on_boarding_state

        # Update the user state to onboarding
        await update_user(user.wa_id, state=UserState.onboarding)

        self.logger.info(
            f"Updated user state to {UserState.onboarding} for user {user.wa_id}"
        )

        # Fetch the appropriate handler for the user's current state
        handler = self.state_handlers.get(user_state, self.handle_default)
        response_text, options = await handler(user)

        self.logger.info(
            f"Processed message for {user.wa_id}: state={user_state} -> response='{response_text}', options={options}"
        )

        return response_text, options


# Instantiate and export the OnboardingHandler client
onboarding_client = OnboardingHandler()
