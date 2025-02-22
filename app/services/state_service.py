import logging

from fastapi.responses import JSONResponse

from app.database.models import Message, User
from app.services.onboarding_service import onboarding_client
from app.database import db
from app.services.whatsapp_service import whatsapp_client
from app.database.enums import MessageRole
from app.utils.string_manager import strings, StringCategory
from app.utils.whatsapp_utils import ValidMessageType, get_valid_message_type
from app.services.messaging_service import messaging_client


class StateHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def handle_blocked(self, user: User) -> JSONResponse:
        assert user.id is not None
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
        assert user.id is not None
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

    async def handle_active(
        self, user: User, message_info: dict, user_message: Message
    ) -> JSONResponse:
        message_type = get_valid_message_type(message_info)
        match message_type:
            case ValidMessageType.SETTINGS_FLOW_SELECTION:
                return await messaging_client.handle_settings_selection(
                    user, user_message
                )
            case ValidMessageType.COMMAND:
                return await messaging_client.handle_command_message(user, user_message)
            case ValidMessageType.CHAT:
                return await messaging_client.handle_chat_message(user, user_message)
            case ValidMessageType.OTHER:
                return await messaging_client.handle_other_message(user, user_message)


state_client = StateHandler()
