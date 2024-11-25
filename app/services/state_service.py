import logging

from fastapi.responses import JSONResponse

from app.database.models import Message, User
from app.services.onboarding_service import onboarding_client
from app.database import db
from app.services.whatsapp_service import whatsapp_client
from app.database.enums import MessageRole
from app.utils.string_manager import strings, StringCategory


class StateHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def handle_blocked(self, user: User) -> JSONResponse:
        response_text = strings.get_string(StringCategory.ERROR, "blocked")
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

    async def handle_rate_limited(self, user: User) -> JSONResponse:
        response_text = strings.get_string(StringCategory.ERROR, "rate_limited")
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


state_client = StateHandler()
