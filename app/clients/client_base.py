import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.messages.base import BaseMessage

from app.clients.whatsapp_client import whatsapp_client
from app.config import Prompt
from app.database.db import create_new_message_by_fields, is_summary_source_eligible
from app.database.enums import MessageRole
from app.database.models import Message, User
from app.services.conversation_summary_runtime import conversation_summary_service
from app.services.conversation_summary_service import (
    PreparedConversation,
    SummaryRequestContext,
    ensure_uncovered,
)
from app.tools.registry import ToolName
from app.tools.tool_manager import ToolManager
from app.utils.message_processor import MessageProcessor
from app.utils.prompt_manager import prompt_manager
from app.utils.string_manager import StringCategory, strings


@dataclass(frozen=True)
class BufferedResponse:
    """Generation was skipped because another request is already processing this user."""

    reason: str = "message_buffered"


BUFFERED_RESPONSE = BufferedResponse()


@dataclass(frozen=True)
class GeneratedResponse:
    messages: list[Message]
    summary_context: SummaryRequestContext


GenerateResponseResult = GeneratedResponse | BufferedResponse | None


class ClientBase(ABC):
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._processors: dict[int, MessageProcessor] = {}
        self.tool_manager = ToolManager()

    def _get_processor(self, user_id: int) -> MessageProcessor:
        """Get or create a message processor for a user."""
        if user_id not in self._processors:
            self._processors[user_id] = MessageProcessor(user_id)
        return self._processors[user_id]

    def _cleanup_processor(self, user_id: int) -> None:
        """Remove processor if it's empty and unlocked."""
        processor = self._processors.get(user_id)
        if processor and not processor.has_messages and not processor.is_locked:
            del self._processors[user_id]

    def _check_new_messages(
        self, processor: MessageProcessor, original_count: int
    ) -> bool:
        """Check if new messages arrived during processing."""
        return len(processor.messages) > original_count

    async def _tool_call_notification(self, user: User, tool_name: str) -> None:
        """Send a notification to the user when a tool call is made."""
        if tool_name == ToolName.search_knowledge.value:
            return  # issue #227
        tool_strings = strings.get_category(StringCategory.TOOLS)

        if tool_name not in tool_strings:
            self.logger.warning(
                f"No notification string defined for tool '{tool_name}'. "
            )
            return

        tool_value = tool_strings[tool_name]

        notification_text: Optional[str]
        if isinstance(tool_value, str):
            notification_text = tool_value
        elif isinstance(tool_value, dict):
            notification_text = tool_value.get("notification")
        else:
            notification_text = None

        if not isinstance(notification_text, str):
            self.logger.warning(
                f"Invalid notification string defined for tool '{tool_name}'. "
            )
            return

        await whatsapp_client.send_message(user.wa_id, notification_text)

        if user.id is None:
            self.logger.warning(
                "Skipping tool notification persistence for user without ID."
            )
            return

        # Kept out of the LLM context (is_present_in_conversation drives
        # get_user_message_history): read back as assistant turns, these status lines
        # taught the agent to reply with a progress message instead of doing the work.
        await create_new_message_by_fields(
            user_id=user.id,
            role=MessageRole.assistant,
            content=notification_text,
            is_present_in_conversation=False,
        )

    async def _preprocess_messages(
        self,
        user: User,
        messages_to_process: tuple[Message, ...],
        prompt: Prompt = Prompt.TWIGA_AGENT_SYSTEM,
    ) -> tuple[list[BaseMessage] | None, SummaryRequestContext | None]:
        if not messages_to_process:
            return None, None
        # The full current interaction stays raw, including inputs above the old
        # character limit. The hard summary service reduces older context first.
        return await self._build_api_messages(user, messages_to_process, prompt)

    async def _build_api_messages(
        self,
        user: User,
        messages_to_process: tuple[Message, ...],
        prompt: Prompt = Prompt.TWIGA_AGENT_SYSTEM,
    ) -> tuple[list[BaseMessage], SummaryRequestContext]:
        prepared = await conversation_summary_service.prepare(
            user.id, messages_to_process
        )
        formatted_messages = self._format_messages(
            list(messages_to_process), None, user, prompt, prepared=prepared
        )

        # Convert to LangChain BaseMessage objects
        # Skip tool-related messages from history for cross-provider compatibility
        # (Some providers like Gemini require tool calls to be immediately followed by tool responses)
        api_messages = []
        for msg_dict in formatted_messages:
            role = msg_dict["role"]
            content = msg_dict["content"] or ""
            if role == "system":
                api_messages.append(SystemMessage(content=content))
            elif role == "user":
                api_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                # Skip assistant messages with tool_calls from history
                if msg_dict.get("tool_calls"):
                    continue
                api_messages.append(AIMessage(content=content))
            elif role == "tool":
                # Skip tool response messages from history
                continue
            else:
                # Fallback to system message
                api_messages.append(SystemMessage(content=content))

        return api_messages, prepared.request

    def _llm_response_to_message(
        self, llm_response: AIMessage, user_id: int
    ) -> Message:
        """Convert a raw LLM response into an assistant Message object."""
        # NOTE: move to helper function
        # Create message from LangChain AIMessage directly
        content_str = None
        if llm_response.content:
            if isinstance(llm_response.content, str):
                content_str = llm_response.content
            elif isinstance(llm_response.content, list):
                # Handle list content by joining or extracting text
                content_str = ""
                for item in llm_response.content:
                    if isinstance(item, str):
                        content_str += item
                    elif isinstance(item, dict) and "text" in item:
                        content_str += item["text"]
            else:
                content_str = str(llm_response.content)

        initial_message = Message(
            user_id=user_id,
            role=MessageRole.assistant,
            content=content_str,
            tool_calls=None,
        )
        return initial_message

    @staticmethod
    def _get_source_chunk_ids(messages: list[Message]) -> list[int]:
        """
        Collect source chunk IDs from tool messages in one response loop.
        The returned list is deduplicated while preserving first-seen order.
        This keeps the result deterministic across runs.

        Inputs:
            - messages: Messages generated in the current thinking loop.

        Returns:
            - List of unique chunk IDs in the order they were first encountered
        """
        if not messages:
            return []

        seen_chunk_ids: set[int] = set()
        ordered_chunk_ids: list[int] = []

        for message in messages:
            if message.role != MessageRole.tool or not message.source_chunk_ids:
                continue

            for chunk_id in message.source_chunk_ids:
                if chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk_id)
                ordered_chunk_ids.append(chunk_id)

        return ordered_chunk_ids

    @staticmethod
    def _format_messages(
        new_messages: list[Message],
        database_messages: Optional[list[Message]],
        user: User,
        prompt: Prompt,
        prepared: PreparedConversation | None = None,
    ) -> list[dict]:
        """
        Format messages for the API, removing duplicates between new messages and database history.
        """
        # Initialize with system prompt
        formatted_messages = [
            {
                "role": MessageRole.system,
                "content": prompt_manager.format_prompt(
                    name=prompt.value,
                    user_name=user.name,
                    class_info=user.formatted_class_info,
                ),
            }
        ]

        if prepared:
            state = prepared.snapshot
            # Inject exactly the persisted/countable text as historical assistant
            # context. It never becomes a new system instruction or user turn.
            if state.older_history_summary:
                formatted_messages.append(
                    {"role": "assistant", "content": state.older_history_summary}
                )
            formatted_messages.extend(
                {"role": "assistant", "content": batch.summary_text}
                for batch in state.active_batches
            )
            database_messages = [
                Message(
                    id=source.id,
                    user_id=user.id,
                    role=source.role,
                    content=source.content,
                    created_at=source.created_at,
                    is_present_in_conversation=True,
                )
                for source in state.pending_sources
            ]

        merged = {}
        for index, message in enumerate((database_messages or []) + new_messages):
            # Unsaved objects remain usable in focused formatter tests; production
            # accepted messages are persisted/validated by the summary service.
            eligible = (
                message
                if message.id is not None
                else message.model_copy(update={"is_present_in_conversation": True})
            )
            if not is_summary_source_eligible(eligible):
                continue
            key = ("id", message.id) if message.id is not None else ("unsaved", index)
            merged[key] = message
        ordered = sorted(
            merged.values(),
            key=lambda m: (
                m.created_at or datetime.min.replace(tzinfo=timezone.utc),
                m.id if m.id is not None else 0,
            ),
        )
        if prepared:
            ensure_uncovered(
                prepared.snapshot,
                frozenset(prepared.request.current_user_message_ids)
                | frozenset(
                    message.id for message in ordered if message.id is not None
                ),
            )
        formatted_messages.extend(message.to_api_format() for message in ordered)

        return formatted_messages

    @abstractmethod
    async def generate_response(
        self,
        user: User,
        message: Message,
    ) -> GenerateResponseResult:
        """Generate a response, handling message batching and tool calls."""
        pass
