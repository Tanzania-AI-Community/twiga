import logging
from typing import Optional

from fastapi.responses import JSONResponse

import app.database.db as db
import app.database.enums as enums
import app.database.models as models
from app.clients.agent_client import agent_client
from app.clients.client_base import ClientBase
from app.clients.llm_client import llm_client
from app.clients.whatsapp_client import DocumentType, ImageType, whatsapp_client
from app.config import llm_settings
from app.latex.latex_artifact_generator import (
    looks_like_latex,
    prepare_latex_body,
    text_to_img,
)
from app.monitoring.metrics import record_messages_generated, track_messages
from app.services.citation_service import CitationRenderResult, citation_service
from app.services.exam_delivery_service import (
    ExamDeliveryMarker,
    ExamPDFDeliveryDetails,
    exam_delivery_service,
)
from app.services.flows.flow_service import flow_client
from app.tools.registry import ToolName
from app.utils.string_manager import StringCategory, strings


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
        if message.content is None:
            raise ValueError("Command message content is unexpectedly None.")
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
        await self._persist_visible_assistant_message(user, response_text)

    @track_messages("command_help")
    async def _command_help(self, user: models.User) -> None:
        response_text = strings.get_string(StringCategory.INFO, "help")
        await whatsapp_client.send_message(user.wa_id, response_text)
        await self._persist_visible_assistant_message(user, response_text)

    @track_messages("command_unknown")
    async def _command_unknown(self, user: models.User) -> None:
        response_text = strings.get_string(StringCategory.ERROR, "command_not_found")
        await whatsapp_client.send_message(user.wa_id, response_text)
        await self._persist_visible_assistant_message(user, response_text)

    async def handle_chat_message(
        self, user: models.User, user_message: models.Message
    ) -> JSONResponse:

        llm_client: ClientBase = self._get_llm_client()
        llm_responses = await llm_client.generate_response(
            user=user, message=user_message
        )

        if not llm_responses:
            await self._handle_no_llm_response(user)
            return JSONResponse(content={"status": "ok"}, status_code=200)

        last_assistant_message = self._get_last_assistant_message(llm_responses)

        if not last_assistant_message:
            await self._handle_missing_assistant_message(user, llm_responses)
            return JSONResponse(content={"status": "ok"}, status_code=200)

        llm_content = last_assistant_message.content

        if llm_content is None:
            raise ValueError("LLM response content is unexpectedly None.")

        if self._are_the_tools_names_mentioned(llm_content):
            await self._handle_tool_leakage(user, llm_responses)
            return JSONResponse(content={"status": "ok"}, status_code=200)

        # NOTE: this changes llm_responses in-place, not very obvious
        last_assistant_message.is_present_in_conversation = False
        await db.create_new_messages(llm_responses)

        if self._should_handle_exam_delivery(llm_responses, llm_content):
            await self._handle_exam_delivery(user, llm_content)
            return JSONResponse(content={"status": "ok"}, status_code=200)

        llm_content = await self._handle_citations(
            llm_content=llm_content,
        )

        if self._is_response_in_latex(llm_content):
            await self._send_latex_response(
                user=user,
                llm_content=llm_content,
                source_chunk_ids=last_assistant_message.source_chunk_ids,
            )
            return JSONResponse(content={"status": "ok"}, status_code=200)

        self.logger.debug(f"Sending message to {user.wa_id}: {llm_content}")
        await self._persist_visible_assistant_message(
            user=user,
            content=llm_content,
            source_chunk_ids=last_assistant_message.source_chunk_ids,
        )

        await whatsapp_client.send_message(user.wa_id, llm_content)
        record_messages_generated("chat_response")

        return JSONResponse(content={"status": "ok"}, status_code=200)

    def _get_llm_client(self) -> ClientBase:
        if llm_settings.agentic_mode:
            self.logger.info(
                "Agentic mode is enabled. Using AgentClient for response generation."
            )
            return agent_client

        self.logger.info(
            "Agentic mode is disabled. Using basic LLMClient for response generation."
        )
        return llm_client

    async def _handle_no_llm_response(self, user: models.User) -> None:
        err_message = strings.get_string(StringCategory.ERROR, "general")
        await whatsapp_client.send_message(user.wa_id, err_message)
        await self._persist_visible_assistant_message(user, err_message)
        record_messages_generated("chat_error")

    def _get_last_assistant_message(
        self, llm_responses: list[models.Message]
    ) -> models.Message | None:
        return next(
            (
                msg
                for msg in reversed(llm_responses)
                if msg.role == enums.MessageRole.assistant and msg.content
            ),
            None,
        )

    async def _handle_missing_assistant_message(
        self, user: models.User, llm_responses: list[models.Message]
    ) -> None:
        self.logger.warning(
            "No assistant response with content available; sending fallback."
        )

        fallback_error_text = strings.get_string(StringCategory.ERROR, "general")
        await whatsapp_client.send_message(user.wa_id, fallback_error_text)
        record_messages_generated("chat_error")

        error_message = models.Message.from_attributes(
            user_id=user.id,
            role=enums.MessageRole.assistant,
            content=fallback_error_text,
        )
        error_message.is_present_in_conversation = True

        messages_to_add = llm_responses + [error_message]
        await db.create_new_messages(messages_to_add)

    async def _handle_tool_leakage(
        self, user: models.User, llm_responses: list[models.Message]
    ) -> None:
        self.logger.warning(
            "Tool name leakage detected in LLM response; sending fallback message."
        )

        tool_leakage_message = strings.get_string(StringCategory.ERROR, "tool_leakage")
        await whatsapp_client.send_message(user.wa_id, tool_leakage_message)
        record_messages_generated("tool_names_mentioned_error")

        error_message = models.Message.from_attributes(
            user_id=user.id,
            role=enums.MessageRole.assistant,
            content=tool_leakage_message,
        )
        error_message.is_present_in_conversation = True

        messages_to_add = llm_responses + [error_message]
        await db.create_new_messages(messages_to_add)

    def _is_response_in_latex(self, llm_content: str) -> bool:
        return looks_like_latex(llm_content)

    async def _send_latex_response(
        self,
        user: models.User,
        llm_content: str,
        source_chunk_ids: list[int] | None = None,
    ) -> None:
        self.logger.debug(f"Sending LaTeX response to {user.wa_id}: {llm_content}")

        await self._persist_visible_assistant_message(
            user=user,
            content=llm_content,
            source_chunk_ids=source_chunk_ids,
        )

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
                return
            else:
                self.logger.warning(
                    "Falling back to plain text delivery; WhatsApp image send failed."
                )
                await whatsapp_client.send_message(user.wa_id, llm_content)
                record_messages_generated("chat_response_with_latex_image_fallback")
                return

        else:
            self.logger.warning(
                "Falling back to plain text delivery; LaTeX render failed."
            )
            await whatsapp_client.send_message(user.wa_id, llm_content)
            record_messages_generated("chat_response_with_latex_image_fallback")

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
        err_message = strings.get_string(StringCategory.ERROR, "unsupported_message")
        await self._persist_visible_assistant_message(user, err_message)

        # Send message to the user
        await whatsapp_client.send_message(wa_id=user.wa_id, message=err_message)
        record_messages_generated("unsupported_message")
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def _persist_visible_assistant_message(
        self,
        user: models.User,
        content: str,
        source_chunk_ids: list[int] | None = None,
    ) -> None:
        if user.id is None:
            self.logger.warning(
                "Skipping assistant message persistence for user without ID."
            )
            return

        await db.create_new_message_by_fields(
            user_id=user.id,
            role=enums.MessageRole.assistant,
            content=content,
            source_chunk_ids=source_chunk_ids,
            is_present_in_conversation=True,
        )

    def _should_handle_exam_delivery(
        self, llm_responses: list[models.Message], llm_content: str
    ) -> bool:
        if self._has_an_exam_been_generated(llm_responses):
            return True

        delivery_marker: ExamDeliveryMarker = (
            exam_delivery_service.parse_delivery_marker(llm_content)
        )
        return delivery_marker.marker_found

    def _has_an_exam_been_generated(self, llm_responses: list[models.Message]) -> bool:
        exam_tool_name = ToolName.generate_necta_style_exam.value

        return any(
            msg.role == enums.MessageRole.tool and msg.tool_name == exam_tool_name
            for msg in llm_responses
        )

    async def _handle_exam_delivery(self, user: models.User, llm_content: str) -> None:
        delivery_marker: ExamDeliveryMarker = (
            exam_delivery_service.parse_delivery_marker(llm_content)
        )

        llm_content = (
            delivery_marker.cleaned_content
            if delivery_marker.marker_found
            else llm_content
        )

        if not delivery_marker.marker_found:
            self.logger.warning(
                "Exam generation tool call detected, but no exam delivery marker was found. "
                "Falling back to the LLM response content."
            )
            self.logger.debug(
                f"Final message content after processing delivery marker: {llm_content}"
            )

            if self._is_response_in_latex(llm_content):
                await self._send_latex_response(user=user, llm_content=llm_content)
                return

            await self._persist_visible_assistant_message(
                user=user, content=llm_content
            )
            await whatsapp_client.send_message(user.wa_id, llm_content)
            record_messages_generated("chat_response")
            return

        self.logger.info(
            f"Exam delivery marker detected. marker_valid={delivery_marker.marker_valid} "
            f"exam_id={delivery_marker.exam_id}"
        )

        if not delivery_marker.marker_valid:
            self.logger.warning(
                "Ignoring invalid exam delivery marker. Falling back to the cleaned LLM response content."
            )
            self.logger.debug(
                f"Final message content after processing delivery marker: {llm_content}"
            )

            if self._is_response_in_latex(llm_content):
                await self._send_latex_response(user=user, llm_content=llm_content)
                return

            await self._persist_visible_assistant_message(
                user=user, content=llm_content
            )
            await whatsapp_client.send_message(user.wa_id, llm_content)
            record_messages_generated("chat_response")
            return

        exam_send_failed = False
        solution_send_failed = False
        exam_subject: Optional[str] = None
        exam_topics: list[str] = []

        if delivery_marker.exam_id:
            exam_details: ExamPDFDeliveryDetails = (
                await exam_delivery_service.get_exam_delivery_details(
                    delivery_marker.exam_id
                )
            )
            exam_subject = exam_details.subject
            exam_topics = exam_details.topics

            if exam_details.errors:
                self.logger.warning(
                    f"Exam artifact preparation issues for exam_id={delivery_marker.exam_id}: "
                    f"{' | '.join(exam_details.errors)}"
                )

            if exam_details.exam_pdf_ready:
                exam_sent = await whatsapp_client.send_document_message(
                    wa_id=user.wa_id,
                    document_path=str(exam_details.exam_pdf_path),
                    doc_type=DocumentType.PDF,
                    filename=exam_details.exam_pdf_path.name,
                )
                if exam_sent:
                    record_messages_generated("exam_pdf_sent")
                else:
                    self.logger.warning(
                        f"Failed to send exam PDF for exam_id={delivery_marker.exam_id}."
                    )
                    record_messages_generated("exam_pdf_send_failed")
                    exam_send_failed = True
            else:
                self.logger.warning(
                    f"Exam PDF artifact not ready for exam_id={delivery_marker.exam_id}."
                )
                exam_send_failed = True

            if exam_details.solution_pdf_ready:
                solution_sent = await whatsapp_client.send_document_message(
                    wa_id=user.wa_id,
                    document_path=str(exam_details.solution_pdf_path),
                    doc_type=DocumentType.PDF,
                    filename=exam_details.solution_pdf_path.name,
                )
                if solution_sent:
                    record_messages_generated("solution_pdf_sent")
                else:
                    self.logger.warning(
                        f"Failed to send solution PDF for exam_id={delivery_marker.exam_id}."
                    )
                    record_messages_generated("solution_pdf_send_failed")
                    solution_send_failed = True
            else:
                self.logger.warning(
                    f"Solution PDF artifact not ready for exam_id={delivery_marker.exam_id}."
                )
                solution_send_failed = True
        else:
            self.logger.warning("Exam delivery marker is valid but exam_id is missing.")
            exam_send_failed = True
            solution_send_failed = True

        exam_delivery_message = self._build_exam_delivery_message(
            subject=exam_subject,
            topics=exam_topics,
            exam_send_failed=exam_send_failed,
            solution_send_failed=solution_send_failed,
        )

        self.logger.debug(
            f"Final message content after processing delivery marker: {exam_delivery_message}"
        )

        if self._is_response_in_latex(exam_delivery_message):
            await self._send_latex_response(
                user=user, llm_content=exam_delivery_message
            )
            return

        await self._persist_visible_assistant_message(
            user=user, content=exam_delivery_message
        )
        await whatsapp_client.send_message(user.wa_id, exam_delivery_message)
        record_messages_generated("chat_response")

    def _build_exam_delivery_message(
        self,
        *,
        subject: Optional[str],
        topics: list[str],
        exam_send_failed: bool,
        solution_send_failed: bool,
    ) -> str:
        tool_name = ToolName.generate_necta_style_exam.value
        tool_strings = strings.get_category(StringCategory.TOOLS).get(tool_name)

        if not isinstance(tool_strings, dict):
            self.logger.error(
                f"Tool strings for '{tool_name}' must be a dictionary with delivery fields."
            )
            record_messages_generated("exam_delivery_string_error")
            return strings.get_string(StringCategory.ERROR, "general")

        def _delivery_message(field: str) -> str:
            value = tool_strings.get(field)
            record_messages_generated(f"exam_{field}")

            if isinstance(value, str):
                return value
            self.logger.error(
                f"Missing or invalid exam delivery field '{field}' in tool strings for '{tool_name}'."
            )
            return strings.get_string(StringCategory.ERROR, "general")

        if exam_send_failed and solution_send_failed:
            return _delivery_message("delivery_failed_exam_and_solution")

        if exam_send_failed:
            return _delivery_message("delivery_failed_exam")

        if solution_send_failed:
            return _delivery_message("delivery_failed_solution")

        subject_text = subject or "the requested subject"
        topics_text = ", ".join(topics) if topics else "the requested topics"

        return _delivery_message("delivery_success").format(
            subject=subject_text,
            topics=topics_text,
        )

    async def _handle_citations(self, llm_content: str) -> str:
        """
        Checks for citation markers in the LLM response content and renders them if found.
        """
        citation_result: CitationRenderResult = await citation_service.render_citations(
            llm_content
        )

        if not citation_result.marker_found:
            return llm_content

        self.logger.info(
            f"Citation marker detected. valid_marker_count={citation_result.valid_reference_count} "
            f"invalid_marker_count={citation_result.invalid_reference_count} "
            f"total_marker_count={citation_result.valid_reference_count + citation_result.invalid_reference_count} "
            f"unique_chunk_ids={len(citation_result.ordered_chunk_ids)}"
        )

        return citation_result.rendered_content


messaging_client = MessagingService()
