import logging

from fastapi.responses import JSONResponse

import app.database.models as models
from app.services.flow_service import flow_client
from app.utils.string_manager import strings, StringCategory
from app.services.whatsapp_service import whatsapp_client, ImageType
import app.database.db as db
from app.services.llm_service import llm_client
from app.services.agent_client import agent_client
from app.config import llm_settings
from app.services.latex_image_service import (
    looks_like_latex,
    prepare_latex_body,
    text_to_img,
)
import app.database.enums as enums
from app.monitoring.metrics import record_messages_generated, track_messages
from app.tools.registry import ToolName


class MessagingService:
    _TOOL_NAME_MARKERS = tuple(tool_name.value for tool_name in ToolName)

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._settings_handlers = {
            "personal info": self._handle_personal_info_settings,
            "classes and subjects": self._handle_classes_subjects_settings,
        }
        self._command_handlers = {
            "settings": self._command_settings,
            "help": self._command_help,
        }

    async def handle_settings_selection(
        self, user: models.User, message: models.Message
    ) -> JSONResponse:
        self.logger.debug(f"Handling interactive message with title: {message.content}")
        key = (message.content or "").strip().lower()
        handler = self._settings_handlers.get(key)
        if handler is None:
            raise Exception(f"Unrecognized user reply: {message.content}")
        await handler(user)
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    @track_messages("settings_flow_personal_info")
    async def _handle_personal_info_settings(self, user: models.User) -> None:
        self.logger.debug("Sending update personal and school info flow")
        await flow_client.send_user_settings_flow(user)

    @track_messages("settings_flow_classes_subjects")
    async def _handle_classes_subjects_settings(self, user: models.User) -> None:
        self.logger.debug("Sending update class and subject info flow")
        await flow_client.send_subjects_classes_flow(user)

    async def handle_command_message(
        self, user: models.User, message: models.Message
    ) -> JSONResponse:
        self.logger.debug(f"Handling command message: {message.content}")
        assert message.content is not None
        key = message.content.lower()
        handler = self._command_handlers.get(key, self._command_unknown)
        await handler(user)
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    @track_messages("command_settings")
    async def _command_settings(self, user: models.User) -> None:
        response_text = strings.get_string(StringCategory.SETTINGS, "intro")
        options = [
            strings.get_string(StringCategory.SETTINGS, "personal_info"),
            strings.get_string(StringCategory.SETTINGS, "class_subject_info"),
        ]
        await whatsapp_client.send_message(user.wa_id, response_text, options)

    @track_messages("command_help")
    async def _command_help(self, user: models.User) -> None:
        response_text = strings.get_string(StringCategory.INFO, "help")
        await whatsapp_client.send_message(user.wa_id, response_text)

    @track_messages("command_unknown")
    async def _command_unknown(self, user: models.User) -> None:
        response_text = strings.get_string(StringCategory.ERROR, "command_not_found")
        await whatsapp_client.send_message(user.wa_id, response_text)

    async def handle_chat_message(
        self, user: models.User, user_message: models.Message
    ) -> JSONResponse:

        if llm_settings.agentic_mode:
            self.logger.info(
                "Agentic mode is enabled. Using AgentClient for response generation."
            )
            llm_responses = await agent_client.generate_response(
                user=user, message=user_message
            )
        else:
            self.logger.info(
                "Agentic mode is disabled. Using standard LLMClient for response generation."
            )
            llm_responses = await llm_client.generate_response(
                user=user, message=user_message
            )

        if llm_responses:
            assert llm_responses[-1].content is not None

            final_message = next(
                (
                    msg
                    for msg in reversed(llm_responses)
                    if msg.role == enums.MessageRole.assistant and msg.content
                ),
                None,
            )

            error_message = None

            if not final_message:
                self.logger.warning(
                    "No assistant response with content available; sending fallback."
                )
                await whatsapp_client.send_message(
                    user.wa_id, strings.get_string(StringCategory.ERROR, "general")
                )
                record_messages_generated("chat_error")

                error_message = models.Message.from_attributes(
                    user_id=user.id,
                    role=enums.MessageRole.assistant,
                    content=strings.get_string(StringCategory.ERROR, "general"),
                )

            llm_content = final_message.content
            if self._are_the_tools_names_mentioned(llm_content):
                self.logger.warning(
                    "Tool name leakage detected in LLM response; sending fallback message."
                )
                await whatsapp_client.send_message(
                    user.wa_id, strings.get_string(StringCategory.ERROR, "tool_leakage")
                )
                record_messages_generated("tool_names_mentioned_error")

                error_message = models.Message.from_attributes(
                    user_id=user.id,
                    role=enums.MessageRole.assistant,
                    content=strings.get_string(StringCategory.ERROR, "tool_leakage"),
                )

            if error_message is not None:
                messages_to_add = llm_responses + [error_message]
                await db.create_new_messages(messages_to_add)

                return JSONResponse(content={"status": "ok"}, status_code=200)

            await db.create_new_messages(llm_responses)

            self.logger.debug(f"Sending message to {user.wa_id}: {llm_content}")

            if looks_like_latex(llm_content):
                prepared_latex_content = prepare_latex_body(llm_content)
                latex_document_path = (
                    text_to_img(prepared_latex_content)
                    if prepared_latex_content is not None
                    else None
                )

                if latex_document_path:
                    image_sent = await whatsapp_client.send_image_message(
                        wa_id=user.wa_id,
                        image_path=latex_document_path,
                        img_type=ImageType.PNG,
                    )
                    if image_sent:
                        record_messages_generated("chat_response_with_latex_image")
                    else:
                        self.logger.warning(
                            "Falling back to plain text delivery; WhatsApp image send failed."
                        )
                        await whatsapp_client.send_message(user.wa_id, llm_content)
                        record_messages_generated(
                            "chat_response_with_latex_image_fallback"
                        )

                else:
                    self.logger.warning(
                        "Falling back to plain text delivery; LaTeX render failed."
                    )
                    await whatsapp_client.send_message(user.wa_id, llm_content)
                    record_messages_generated("chat_response_with_latex_image_fallback")

            else:
                await whatsapp_client.send_message(user.wa_id, llm_content)
                record_messages_generated("chat_response")

        else:
            err_message = strings.get_string(StringCategory.ERROR, "general")
            await whatsapp_client.send_message(user.wa_id, err_message)
            record_messages_generated("chat_error")

        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    def _are_the_tools_names_mentioned(self, message: str) -> bool:
        tool_names = self._TOOL_NAME_MARKERS
        if not tool_names:
            return False

        message_lower = message.lower()
        for tool_name in tool_names:
            if tool_name in message_lower:
                return True

        return False

    async def handle_other_message(
        self, user: models.User, user_message: models.Message
    ) -> JSONResponse:
        assert user.id is not None
        message = models.Message(
            user_id=user.id,
            role=enums.MessageRole.assistant,
            content=strings.get_string(StringCategory.ERROR, "unsupported_message"),
        )
        await db.create_new_message(message)
        # Send message to the user
        await whatsapp_client.send_message(
            user.wa_id, strings.get_string(StringCategory.ERROR, "unsupported_message")
        )
        record_messages_generated("unsupported_message")
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )


messaging_client = MessagingService()
