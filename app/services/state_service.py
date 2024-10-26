import logging
from typing import List, Optional, Tuple, Dict, Callable

from app.database.models import User, UserState

class StateHandler:
    def __init__(self):
        # Define the mapping of states to handler methods
        self.state_handlers: Dict[
            UserState, Callable[[User, str, UserState], Tuple[str, Optional[List[str]]]]
        ] = {
            UserState.onboarding: self.handle_onboarding,
            UserState.active: self.handle_active,
            UserState.inactive: self.handle_inactive,
            UserState.opted_out: self.handle_opted_out,
            UserState.new: self.handle_new,
            UserState.blocked: self.handle_blocked,
            UserState.rate_limited: self.handle_rate_limited,
            UserState.has_pending_message: self.handle_has_pending_message,
        }

        self.logger = logging.getLogger(__name__)

    def handle_default(self, user: User, message_body: str, user_state: UserState) -> Tuple[str, Optional[List[str]]]:
        response_text = "Your current state is not recognized. Please contact support."
        options = None
        return response_text, options

    def handle_onboarding(self, user: User, message_body: str, user_state: UserState) -> Tuple[str, Optional[List[str]]]:
        response_text = "You are currently in the onboarding process. Please complete the onboarding steps."
        options = ["Continue Onboarding"]
        return response_text, options
    
    def handle_active(self, user: User, message_body: str, user_state: UserState) -> Tuple[None, None]:
        # User is active, proceed with normal conversation
        return None, None
    
    def handle_inactive(self, user: User, message_body: str, user_state: UserState) -> Tuple[str, Optional[List[str]]]:
        response_text = "Your account is inactive. Please send a message to reactivate your account."
        options = None
        return response_text, options

    def handle_opted_out(self, user: User, message_body: str, user_state: UserState) -> Tuple[str, Optional[List[str]]]:
        response_text = "You have opted out of the service. Please contact support if you wish to opt back in."
        options = None
        return response_text, options

    def handle_new(self, user: User, message_body: str, user_state: UserState) -> Tuple[str, Optional[List[str]]]:
        response_text = "Welcome! Please complete the onboarding process to start using the service."
        options = ["Start Onboarding"] # TODO: handle this reply, when we receive it after we have the onboarding process
        return response_text, options

    def handle_blocked(self, user: User, message_body: str, user_state: UserState) -> Tuple[str, Optional[List[str]]]:
        response_text = "Your account is currently blocked. Please contact support for assistance."
        options = None
        return response_text, options

    def handle_rate_limited(self, user: User, message_body: str, user_state: UserState) -> Tuple[str, Optional[List[str]]]:
        response_text = "You have reached the rate limit for messages. Please try again in a few minutes."
        options = ["Retry"] # TODO: handle this reply, when we receive it after the rate limit is over, we can send the message again
        return response_text, options

    def handle_has_pending_message(self, user: User, message_body: str, user_state: UserState) -> Tuple[str, Optional[List[str]]]:
        response_text = "You have a pending message. Please wait for a response before sending a new message."
        options = None
        return response_text, options

    def process_state(
            self, user: User, message_body: str
        ) -> Tuple[str, Optional[List[str]]]:
        # Get the user's current state from the user object
        user_state = user.state

        # Fetch the appropriate handler for the user's current state
        handler = self.state_handlers.get(user_state, self.handle_default)
        response_text, options = handler(user, message_body, user_state)

        self.logger.debug(
            f"Processed message for {user.wa_id}: state={user_state}, message='{message_body}' -> response='{response_text}', options={options}"
        )

        return response_text, options

state_client = StateHandler()