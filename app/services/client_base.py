import logging
from typing import Optional
from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    AIMessage,
)
from langchain_core.messages.base import BaseMessage
from app.database.models import Message, User
from app.database.enums import MessageRole
from app.database.db import get_user_message_history
from app.utils.prompt_manager import prompt_manager
from app.utils.message_processor import MessageProcessor
from app.services.whatsapp_service import whatsapp_client
from app.utils.string_manager import strings, StringCategory
from app.tools.tool_manager import ToolManager
from abc import ABC, abstractmethod
import base64


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
        await whatsapp_client.send_message(
            user.wa_id, strings.get_string(StringCategory.TOOLS, tool_name)
        )

    async def _build_api_messages(
        self,
        user: User,
        messages_to_process: list[Message],
    ) -> list[BaseMessage]:
        """Build the API messages from DB history + new messages"""

        self.logger.debug("Retrieving user message history")
        history = await get_user_message_history(user.id)

        formatted_messages = self._format_messages(messages_to_process, history, user)

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
                media_id = msg_dict.get("media_id")
                mime_type = msg_dict.get("mime_type")
                if media_id and mime_type:
                    image_bytes, _ = await whatsapp_client.download_media(media_id)
                    base64_url = self._encode_image_to_base64(image_bytes, mime_type)
                    multimodal_content = []
                    multimodal_content.append({"type": "text", "text": content})
                    multimodal_content.append({"type": "image_url","image_url": {"url": base64_url}})
                    api_messages.append(HumanMessage(content=multimodal_content))
                else:
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

        return api_messages

    def _encode_image_to_base64(self, image_bytes: bytes, mime_type: str) -> str:
        """Encodes image bytes to a Base64 data URL string"""
        base64_encoded_data = base64.b64encode(image_bytes)
        base64_string = base64_encoded_data.decode('utf-8') 
        return f"data:{mime_type};base64,{base64_string}"

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
    def _format_messages(
        new_messages: list[Message],
        database_messages: Optional[list[Message]],
        user: User,
    ) -> list[dict]:
        """
        Format messages for the API, removing duplicates between new messages and database history.
        """
        # Initialize with system prompt
        formatted_messages = [
            {
                "role": MessageRole.system,
                "content": prompt_manager.format_prompt(
                    "twiga_system",
                    user_name=user.name,
                    class_info=user.formatted_class_info,
                ),
            }
        ]

        # Add history messages
        if database_messages:
            # Exclude potential duplicates
            message_count = len(new_messages)
            db_message_count = len(database_messages)

            # Safety check: ensure we don't slice more messages than we have
            if db_message_count < message_count:
                raise Exception(
                    f"Unusual message count scenario detected: There are {message_count} new messages but only {db_message_count} messages in the database."
                )

            old_messages = (
                database_messages[:-message_count]
                if message_count > 0
                else database_messages
            )
            formatted_messages.extend(msg.to_api_format() for msg in old_messages)

        # Add new messages
        formatted_messages.extend(msg.to_api_format() for msg in new_messages)

        return formatted_messages

    @abstractmethod
    async def generate_response(
        self,
        user: User,
        message: Message,
    ) -> Optional[list[Message]]:
        """Generate a response, handling message batching and tool calls."""
        pass
