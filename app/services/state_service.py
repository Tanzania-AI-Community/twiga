import logging

from fastapi.responses import JSONResponse

from app.database.models import Message, OnboardingState, User, UserState
from app.database.models import Role
from app.services.onboarding_service import onboarding_client
from app.database import db
from app.services.whatsapp_service import whatsapp_client
from app.database.enums import MessageRole


class StateHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def handle_blocked(self, user: User) -> JSONResponse:
        response_text = "Your account is currently blocked. Please contact support (dev@ai.or.tz) for assistance."
        await whatsapp_client.send_message(user.wa_id, response_text)
        await db.create_new_message(
            Message(
                user_id=user.id,
                role=MessageRole.assistant,
                content=response_text,
            )
        )
        # TODO: Alternatively return a response indicating user is blocked for WhatsApp
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def handle_rate_limited(self, user: User) -> JSONResponse:
        response_text = "🚫 You have reached your daily messaging limit, so Twiga 🦒 is quite sleepy from all of today's texting 🥱. Let's talk more tomorrow!"
        await whatsapp_client.send_message(user.wa_id, response_text)
        await db.create_new_message(
            Message(
                user_id=user.id,
                role=MessageRole.assistant,
                content=response_text,
            )
        )
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def handle_onboarding(self, user: User) -> JSONResponse:
        await onboarding_client.process_state(user)
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def handle_new_dummy(self, user: User) -> JSONResponse:
        user.state = UserState.active
        user.role = Role.teacher
        await db.add_default_subjects_and_classes()
        dummy_selected_classes = ["1"]
        dummy_selected_subject = "1"
        dummy_selected_subject_formatted = int(dummy_selected_subject)
        dummy_selected_classes_formatted = [
            int(class_id) for class_id in dummy_selected_classes
        ]
        user.selected_class_ids = dummy_selected_classes_formatted
        user = await db.update_user_selected_classes(
            user, dummy_selected_classes_formatted, dummy_selected_subject_formatted
        )
        user.state = UserState.active
        user.onboarding_state = OnboardingState.completed

        # Update the database accordingly
        user = await db.update_user(user)
        await db.add_teacher_class(user, dummy_selected_classes_formatted)

        response_text = "Welcome to Twiga! 🦒 Looks like Auto Onboarding is on, Default Subject and Classes have been set for you. 🎉. You may as your questions"
        await whatsapp_client.send_message(user.wa_id, response_text)
        await db.create_new_message(
            Message(
                user_id=user.id,
                role=MessageRole.assistant,
                content=response_text,
            )
        )

        self.logger.warning(f"User {user.wa_id} was given dummy data for development")
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )


state_client = StateHandler()
