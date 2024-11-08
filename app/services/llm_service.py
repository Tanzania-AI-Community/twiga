import json
import logging
import asyncio
from typing import Dict, List, Optional
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageToolCall

from app.database.models import Message, MessageRole, User
from app.config import llm_settings
from app.database.db import get_user_message_history
from app.services.whatsapp_service import (
    whatsapp_client,
)  # TODO: send updates to user during tool calls
from app.utils.llm_utils import async_llm_request
from assets.preprompts.prompts import get_system_prompt
from app.tools.registry import tools_functions, tools_metadata


class MessageProcessor:
    """Handles processing and batching of messages for a single user."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.lock = asyncio.Lock()
        self.messages: List[str] = []

    def add_message(self, message: str) -> None:
        self.messages.append(message)

    def get_pending_messages(self) -> List[str]:
        return self.messages.copy()

    def clear_messages(self) -> None:
        self.messages.clear()

    @property
    def has_messages(self) -> bool:
        return bool(self.messages)

    @property
    def is_locked(self) -> bool:
        return self.lock.locked()


class LLMClient:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url="https://api.together.xyz/v1",
            api_key=llm_settings.llm_api_key.get_secret_value(),
        )
        self.logger = logging.getLogger(__name__)
        self._processors: dict[int, MessageProcessor] = {}
        # self._user_locks = {}  # {user_id: Lock()}
        # self._message_buffers = {}  # {user_id: ["message1", "message2"]}

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
        self, processor: MessageProcessor, original_buffer: List[str]
    ) -> bool:
        """Check if new messages arrived during processing."""
        return len(processor.messages) > len(original_buffer)

    async def _process_tool_calls(
        self,
        tool_calls: List[ChatCompletionMessageToolCall],
        user: User,
        resources: Optional[List[int]] = None,
    ) -> Optional[List[dict]]:
        """Process tool calls and return just the new tool response messages.

        Args:
            messages: Current message history (not modified)
            tool_calls: List of tool calls to process

        Returns:
            List[dict]: Only the new tool response messages
        """
        tool_responses = []
        if resources:
            self.logger.debug(f"Resources available: {resources}")
            # Process each tool call and collect results
            for tool_call in tool_calls:
                try:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    # TODO: Make this modular, depending on what the tools available are
                    function_args["user"] = user  # Each tool gets the user object
                    function_args["resources"] = (
                        resources  # Each tool gets the resource ids
                    )

                    if function_name in tools_functions:
                        tool_func = tools_functions[function_name]
                        result = (
                            await tool_func(**function_args)
                            if asyncio.iscoroutinefunction(tool_func)
                            else tool_func(**function_args)
                        )

                        tool_responses.append(
                            {
                                "role": MessageRole.tool,
                                "content": json.dumps(result),
                                "tool_call_id": tool_call.id,
                            }
                        )
                except Exception as e:
                    self.logger.error(f"Error in {function_name}: {str(e)}")
                    tool_responses.append(
                        {
                            "role": MessageRole.tool,
                            "content": json.dumps({"error": str(e)}),
                            "tool_call_id": tool_call.id,
                        }
                    )

            return tool_responses
        else:
            self.logger.error("No resources available for tool calls")
            tool_responses.append(
                {
                    "role": MessageRole.system,
                    "content": json.dumps(
                        {
                            "error": "Tools are not available right now, no available resources."
                        }
                    ),
                }
            )
            return None

    async def generate_response(
        self,
        user: User,
        message: Message,
        resources: Optional[List[int]] = None,
    ) -> Optional[List[Message]]:
        """Generate a response, handling message batching and tool calls."""
        processor = self._get_processor(user.id)
        processor.add_message(message.content)

        self.logger.debug(
            f"Message buffer for user: {user.wa_id}, buffer: {processor.get_pending_messages()}"
        )

        if processor.is_locked:
            self.logger.info(f"Lock held for user {user.id}, message buffered")
            return None

        async with processor.lock:
            while True:
                try:
                    messages_to_process = processor.get_pending_messages()

                    if not messages_to_process:
                        self.logger.warning(
                            f"This shouldn't happen. No messages to process for user {user.id}."
                        )
                        processor.clear_messages()
                        self._cleanup_processor(user.id)
                        return None

                    # Fetch messages and format into API-ready messages
                    history_objects = await get_user_message_history(user.id)
                    messages = self._format_messages(
                        messages_to_process=messages_to_process,
                        database_messages=history_objects,
                        user=user,
                    )

                    self.logger.debug(
                        "Initial messages:\n" + json.dumps(messages, indent=2)
                    )

                    # Track new messages from this interaction
                    new_messages: List[Message] = []

                    # Initial generation with tools enabled
                    initial_response = await async_llm_request(
                        model=llm_settings.llm_model_name,
                        messages=messages,
                        tools=tools_metadata,
                        tool_choice="auto",
                        temperature=0.5,
                    )

                    self.logger.debug(
                        "LLM response:\n"
                        + json.dumps(
                            initial_response.choices[0].message.model_dump(), indent=2
                        )
                    )

                    # Check for new messages
                    if self._check_new_messages(processor, messages_to_process):
                        self.logger.warning(
                            "New messages arrived during llm processing, restarting"
                        )
                        continue

                    # Process tool calls if present
                    if initial_response.choices[0].message.tool_calls:
                        self.logger.debug("Processing tool calls 🛠️")

                        # Add tool calls message to tracking
                        tool_calls_message = {
                            "role": MessageRole.assistant,
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": tool_call.id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_call.function.name,
                                        "arguments": tool_call.function.arguments,
                                    },
                                }
                                for tool_call in initial_response.choices[
                                    0
                                ].message.tool_calls
                            ],
                        }
                        messages.append(tool_calls_message)
                        new_messages.append(
                            self._create_message_object(tool_calls_message, user.id)
                        )

                        # Process tool calls and track the tool response messages
                        tool_responses = await self._process_tool_calls(
                            initial_response.choices[0].message.tool_calls,
                            user,
                            resources,
                        )

                        messages.extend(tool_responses)
                        new_messages.extend(
                            self._create_message_objects(tool_responses, user.id)
                        )

                        self.logger.debug(
                            "Updated messages:\n" + json.dumps(messages, indent=2)
                        )

                        final_response = await async_llm_request(
                            model=llm_settings.llm_model_name,
                            messages=messages,
                            tools=None,
                            tool_choice=None,
                        )

                        # Add final_response to messages
                        messages.append(
                            {
                                "role": MessageRole.assistant,
                                "content": final_response.choices[0].message.content,
                            }
                        )

                        # Check for new messages again
                        if self._check_new_messages(processor, messages_to_process):
                            self.logger.warning(
                                "New messages arrived during processing of tools, restarting"
                            )
                            continue

                        final_message = {
                            "role": MessageRole.assistant,
                            "content": final_response.choices[0].message.content,
                        }
                    else:
                        # If no tool calls, use the initial response as the final message
                        final_message = {
                            "role": MessageRole.assistant,
                            "content": initial_response.choices[0].message.content,
                        }

                    # Success - clear buffer and return response
                    self.logger.info("Message processing complete, clearing buffer")
                    processor.clear_messages()
                    self._cleanup_processor(user.id)

                    new_messages.append(
                        self._create_message_object(final_message, user.id)
                    )

                    return new_messages

                except Exception as e:
                    self.logger.error(f"Error processing messages: {e}")
                    processor.clear_messages()
                    self._cleanup_processor(user.id)
                    return None

    def _format_messages(
        self,
        messages_to_process: List[str],
        database_messages: List[Message],
        user: User,
    ) -> List[dict]:
        """
        Format messages for the API, removing duplicates between new messages and database history.

        Args:
            messages_to_process: List of new messages to be processed
            database_messages: List of messages from database history

        Returns:
            List[dict]: Formatted messages with system prompt, history, and new messages
        """
        # Initialize with system prompt
        formatted_messages = [
            {
                "role": MessageRole.system,
                "content": get_system_prompt(user, "default_system"),
            }
        ]

        # If we have messages in the database, add all except the most recent duplicates
        if database_messages:
            message_count = len(messages_to_process)
            db_message_count = len(database_messages)

            # Safety check: ensure we don't slice more messages than we have
            messages_to_keep = max(0, db_message_count - message_count)

            # Add messages from database, excluding potential duplicates
            formatted_messages.extend(
                {"role": msg.role, "content": msg.content}
                for msg in database_messages[:messages_to_keep]
            )

            if db_message_count < message_count:
                self.logger.warning(
                    f"Unusual message count scenario detected: {message_count} new messages, "
                    f"but only {db_message_count} messages in database. Using only new messages."
                )

        # Add each new message separately
        formatted_messages.extend(
            {"role": MessageRole.user, "content": msg} for msg in messages_to_process
        )

        return formatted_messages

    def _create_message_object(self, message: Dict[str, str], user_id: int) -> Message:
        """Create a Message object from a message dict."""
        try:
            # Handle tool calls differently
            content = message.get("content", "")
            if message.get("tool_calls"):
                content = json.dumps(message.get("tool_calls"))

            # Create Message object
            message_object = Message(
                user_id=user_id,
                content=content,
                role=message["role"],
            )

            # Handle tool responses differently
            if message.get("tool_call_id"):
                message_object.content = json.dumps(
                    {
                        "content": content,
                        "tool_call_id": message["tool_call_id"],
                    }
                )

            return message_object
        except KeyError as e:
            self.logger.error(f"Missing required field in message: {e}")
        except Exception as e:
            self.logger.error(f"Error converting message: {e}")

    def _create_message_objects(
        self, messages: List[Dict[str, str]], user_id: int
    ) -> List[Message]:
        """Convert LLM messages to Message objects."""
        message_objects: List[Message] = []

        for message in messages:
            message_objects.append(self._create_message_object(message, user_id))

        return message_objects


llm_client = LLMClient()
