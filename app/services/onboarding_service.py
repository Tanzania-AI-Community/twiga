import logging
from typing import List, Optional, Tuple, Dict, Callable

from db.utils import AppDatabase


class OnboardingHandler:
    def __init__(self):
        # Define the mapping of states to handler methods
        self.state_handlers: Dict[
            str, Callable[[str, str, dict], Tuple[str, Optional[List[str]]]]
        ] = {
            "start": self.handle_start,
            "ask_teacher": self.handle_ask_teacher,
            "ask_subject": self.handle_ask_subject,
            "ask_form": self.handle_ask_form,
            "completed": self.handle_completed,
        }

        # Define static choices for options
        self.subjects = ["Geography"]
        self.forms = ["Form 1", "Form 2", "Form 3", "Form 4"]
        self.logger = logging.getLogger(__name__)
        self.db = AppDatabase()

    def handle_start(
        self, wa_id: str, message_body: str, state: dict
    ) -> Tuple[str, List[str]]:
        self.db.update_user_state(wa_id, {"state": "ask_teacher"})
        return (
            "Hello! My name is Twiga 🦒, I am a WhatsApp bot that supports teachers in the TIE curriculum with their daily tasks. \n\nAre you a TIE teacher?",
            ["Yes", "No"],
        )

    def handle_ask_teacher(
        self, wa_id: str, message_body: str, state: dict
    ) -> Tuple[str, Optional[List[str]]]:
        message_body_lower = message_body.lower()
        if message_body_lower == "yes":
            self.db.update_user_state(wa_id, {"state": "ask_subject"})
            return "What subject do you teach?", self.subjects
        elif message_body_lower == "no":
            return (
                "This service is for teachers only. Please select yes if you would like further support. Are you a teacher?",
                ["Yes", "No"],
            )
        else:
            return "Please select *Yes* or *No*. Are you a teacher?", ["Yes", "No"]

    def handle_ask_subject(
        self, wa_id: str, message_body: str, state: dict
    ) -> Tuple[str, List[str]]:
        if message_body in self.subjects:
            self.db.update_user_state(
                wa_id, {"state": "ask_form", "subject": message_body}
            )
            return "Which form do you teach?", self.forms
        else:
            return "Please select a valid subject from the list.", self.subjects

    def handle_ask_form(
        self, wa_id: str, message_body: str, state: dict
    ) -> Tuple[str, List[str]]:
        if message_body in self.forms:
            subject = state.get("subject")
            form = message_body
            form = "Form 2"  # Temporary addition for the beta

            self.db.update_user_state(
                wa_id, {"state": "completed", "subject": subject, "form": form}
            )
            # TODO: This could also be a template message
            welcome_message = (
                f"Welcome! You teach *{subject}* to *{form}*. \n\nYou might have noticed that Geography Form 2 was the only possible choice. "
                "That's because I, Twiga 🦒, am currently being tested with a limited set of data. \n\n"
                "Currently, I can help you with the following tasks: \n"
                "1. Generate an exercise or question for your students based on the TIE Form 2 Geography book. \n"
                "2. Provide general assistance with Geography. \n\n"
                "How can I assist you today?"
            )

            return welcome_message, None
        else:
            return "Please select a valid form from the list.", self.forms

    def handle_completed(
        self, wa_id: str, message_body: str, state: dict
    ) -> Tuple[None, None]:
        # Onboarding complete, proceed with normal conversation
        return None, None

    def handle_default(self, wa_id: str) -> Tuple[str, List[str]]:
        self.db.update_user_state(wa_id, {"state": "ask_teacher"})
        return "I'm not sure how to proceed. Let's start over. Are you a teacher?", [
            "Yes",
            "No",
        ]

    def process_state(
        self, wa_id: str, message_body: str
    ) -> Tuple[str, Optional[List[str]]]:
        # Get the user's current state
        state = self.db.get_user_state(wa_id)
        user_state = state.get("state", "start")

        # Fetch the appropriate handler for the user's current state
        handler = self.state_handlers.get(user_state, self.handle_default)
        response_text, options = handler(wa_id, message_body, state)

        self.logger.debug(
            f"Processed message for {wa_id}: state={user_state}, message='{message_body}' -> response='{response_text}', options={options}"
        )

        return response_text, options


onboarding_client = OnboardingHandler()
