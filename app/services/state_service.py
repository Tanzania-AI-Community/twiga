import logging
from typing import List, Optional, Tuple, Dict, Callable

from fastapi.responses import JSONResponse

from app.database.models import Message, MessageRole, User, UserState
from app.database.models import ClassInfo, GradeLevel, Role, Subject, User, UserState
from app.services.onboarding_service import onboarding_client
from app.config import settings
from app.database import db
from app.utils.whatsapp_utils import generate_payload
from app.services.whatsapp_service import whatsapp_client


class StateHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    # TODO: all manually written messages should be moved to a separate file
    def handle_default(self) -> Tuple[str, Optional[List[str]]]:
        response_text = "There appears to have occurred an error. Please contact support (dev@ai.or.tz) for assistance."
        return response_text

    async def handle_blocked(self, user: User) -> JSONResponse:
        response_text = "Your account is currently blocked. Please contact support (dev@ai.or.tz) for assistance."
        payload = generate_payload(user.wa_id, response_text)
        await whatsapp_client.send_message(payload)
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
        payload = generate_payload(user.wa_id, response_text)
        await whatsapp_client.send_message(payload)
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


state_client = StateHandler()
