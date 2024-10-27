import logging
from typing import List, Optional, Tuple, Dict, Callable

from app.database.models import User, UserState


class StateHandler:
    def __init__(self):
        # Define the mapping of states to handler methods
        self.state_handlers: Dict[
            UserState, Callable[[User, UserState], Tuple[str, Optional[List[str]]]]
        ] = {
            UserState.new: self.handle_new,
            UserState.blocked: self.handle_blocked,
            UserState.rate_limited: self.handle_rate_limited,
            UserState.has_pending_message: self.handle_has_pending_message,  # TODO: determine if this is the right approach
        }

        self.logger = logging.getLogger(__name__)

    # TODO: all manually written messages should be moved to a separate file
    def handle_default(
        self, user: User, user_state: UserState
    ) -> Tuple[str, Optional[List[str]]]:
        response_text = "There appears to have occurred an error. Please contact support (dev@ai.or.tz) for assistance."
        return response_text, None

    def handle_new(
        self, user: User, user_state: UserState
    ) -> Tuple[str, Optional[List[str]]]:
        response_text = "Welcome! Please complete the onboarding process to start using the service."
        return response_text, None

    def handle_blocked(
        self, user: User, user_state: UserState
    ) -> Tuple[str, Optional[List[str]]]:
        response_text = "Your account is currently blocked. Please contact support (dev@ai.or.tz) for assistance."
        return response_text, None

    def handle_rate_limited(
        self, user: User, user_state: UserState
    ) -> Tuple[str, Optional[List[str]]]:
        response_text = "🚫 You have reached your daily messaging limit, so Twiga 🦒 is quite sleepy from all of today's texting 🥱. Let's talk more tomorrow!"
        return response_text, None

    def handle_has_pending_message(
        self, user: User, user_state: UserState
    ) -> Tuple[str, Optional[List[str]]]:
        response_text = "You have a pending message. Please wait for a response before sending a new message."
        options = None
        return response_text, options

    def process_state(self, user: User) -> Tuple[str, Optional[List[str]]]:

        # Get the user's current state from the user object
        user_state = user.state

        # If the user is active or onboarding return None to indicate that the message should be processed differently than an automated response
        if user_state == UserState.active or user_state == UserState.onboarding:
            return None, None

        # Fetch the appropriate handler for the user's current state
        handler = self.state_handlers.get(user_state, self.handle_default)
        response_text, options = handler(user, user_state)

        return response_text, options


state_client = StateHandler()