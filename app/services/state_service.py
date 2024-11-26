import logging

from fastapi.responses import JSONResponse

from app.database.models import Message, User
from app.services.onboarding_service import onboarding_client
from app.database import db
from app.services.whatsapp_service import whatsapp_client
from app.database.enums import MessageRole
from app.utils.string_manager import strings, StringCategory
from app.utils.whatsapp_utils import ValidMessageType, get_valid_message_type
from app.services.llm_service import llm_client
from app.services.flow_service import flow_client


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

    async def handle_active(
        self, user: User, message_info: dict, user_message: Message
    ) -> JSONResponse:
        message_type = get_valid_message_type(message_info)
        match message_type:
            case ValidMessageType.SETTINGS_FLOW_SELECTION:
                return await self._handle_settings_selection(user, user_message)
            case ValidMessageType.COMMAND:
                return await self._handle_command_message(user, user_message)
            case ValidMessageType.CHAT:
                return await self._handle_chat_message(user, user_message)

    async def _handle_settings_selection(
        self, user: User, message: Message
    ) -> JSONResponse:
        self.logger.debug(f"Handling interactive message with title: {message.content}")
        if message.content == "Personal Info":
            self.logger.debug("Sending update personal and school info flow")
            await flow_client.send_personal_and_school_info_flow(user, is_update=True)
        elif message.content == "Classes and Subjects":
            self.logger.debug("Sending update class and subject info flow")
            await flow_client.send_select_subject_flow(user, is_update=True)
        else:
            raise Exception(f"Unrecognized user reply: {message.content}")
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def _handle_command_message(self, user: User, message: Message) -> JSONResponse:  # type: ignore
        self.logger.debug(f"Handling command message: {message.content}")
        if message.content.lower() == "settings":
            response_text = strings.get_string(StringCategory.SETTINGS, "intro")
            options = [
                strings.get_string(StringCategory.SETTINGS, "personal_info"),
                strings.get_string(StringCategory.SETTINGS, "class_subject_info"),
            ]
            await whatsapp_client.send_message(user.wa_id, response_text, options)
        elif message.content.lower() == "help":
            response_text = strings.get_string(StringCategory.INFO, "help")
            await whatsapp_client.send_message(user.wa_id, response_text)
        else:
            response_text = strings.get_string(
                StringCategory.ERROR, "command_not_found"
            )
            await whatsapp_client.send_message(user.wa_id, response_text)
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def _handle_chat_message(
        self, user: User, user_message: Message
    ) -> JSONResponse:
        available_user_resources = await db.get_user_resources(user)
        llm_responses = await llm_client.generate_response(
            user=user, message=user_message, resources=available_user_resources
        )
        if llm_responses:
            self.logger.debug(
                f"Sending message to {user.wa_id}: {llm_responses[-1].content}"
            )

            # Update the database with the responses
            llm_responses = await db.create_new_messages(llm_responses)

            # Send the last message back to the user
            await whatsapp_client.send_message(user.wa_id, llm_responses[-1].content)
        else:
            self.logger.error("No responses generated by LLM")
            err_message = strings.get_string(StringCategory.ERROR, "general")
            await whatsapp_client.send_message(user.wa_id, err_message)

        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )


state_client = StateHandler()
