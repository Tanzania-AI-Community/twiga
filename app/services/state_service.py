import logging
from typing import List, Optional, Tuple, Dict, Callable

from app.database.db import update_user_by_waid
from app.database.models import User, UserState
from app.services.onboarding_service import onboarding_client
from app.config import settings

logger = logging.getLogger(__name__)


class StateHandler:
    def __init__(self):
        # Define the mapping of states to handler methods
        self.state_handlers: Dict[
            UserState, Callable[[User, UserState], Tuple[str, Optional[List[str]]]]
        ] = {
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

    async def process_state(self, user: User) -> Tuple[str, Optional[List[str]], bool]:
        user_state = user.state

        logger.info(
            f"Processing state for user {user.name} with wa_id {user.wa_id} and user state {user_state}"
        )

        # If the user is active  return None to indicate that the message should be processed differently than an automated response
        if user_state == UserState.active:
            return None, None, False

        if user_state == UserState.onboarding or UserState.new:
            if not settings.business_env and user.state == UserState.new:
                # TODO: Update user state to active and set them as a Geography Form 2 Teacher (alternatively, create custom onboarding)
                self.logger.info(
                    "User is new and in development environment. Setting user as active with dummy data."
                )
                pass
            else:
                await onboarding_client.process_state(user)
            return None, None, True

        # Fetch the appropriate handler for the user's current state
        handler = self.state_handlers.get(user_state, self.handle_default)
        response_text, options = handler(user, user_state)

        return response_text, options, True


state_client = StateHandler()
