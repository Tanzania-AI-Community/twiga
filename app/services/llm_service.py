import json
import logging
import asyncio
from typing import Any, Callable, Dict, List, Optional, Tuple
from together import AsyncTogether
from openai import AsyncOpenAI


from app.database.models import Message, MessageRole, User
from app.config import llm_settings
from app.database.db import get_user_message_history
from app.services.whatsapp_service import (
    whatsapp_client,
)  # TODO: send updates to user during tool calls
from assets.prompts import get_system_prompt
from app.tools.registry import tools_functions, tools_metadata, ToolName


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
            api_key=llm_settings.together_api_key.get_secret_value(),
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

    async def _check_new_messages(
        self, processor: MessageProcessor, original_count: int
    ) -> bool:
        """Check if new messages arrived during processing."""
        return len(processor.messages) > original_count

    # def _get_user_lock(self, user_id: int) -> asyncio.Lock:
    #     """Get or create a lock for a specific user."""
    #     if user_id not in self._user_locks:
    #         self._user_locks[user_id] = asyncio.Lock()
    #     return self._user_locks[user_id]

    # def _get_message_buffer(self, user_id: int) -> list:
    #     """Get or create a message buffer for a specific user."""
    #     if user_id not in self._message_buffers:
    #         self._message_buffers[user_id] = []
    #     return self._message_buffers[user_id]

    # def _cleanup_user(self, user_id: int):
    #     """Remove user's lock and buffer if they're empty."""
    #     if user_id in self._message_buffers and not self._message_buffers[user_id]:
    #         del self._message_buffers[user_id]
    #     if user_id in self._user_locks and not self._user_locks[user_id].locked():
    #         del self._user_locks[user_id]

    # TODO: this might best be done in the llm_utils file
    async def _generate_completion(
        self, messages: List[dict], include_tools: bool = True
    ) -> Optional[Dict]:
        """Generate a completion from the API with optional tool support."""
        try:
            response = await self.client.chat.completions.create(
                model=llm_settings.llm_model_name,
                messages=messages,
                tools=tools_metadata if include_tools else None,
                tool_choice="auto" if include_tools else None,
            )
            return response.choices[0].message
        except Exception as e:
            self.logger.error(f"Error generating completion: {str(e)}")
            return None

    async def _process_tool_calls(
        self, messages: List[dict], tool_calls: List[Any]
    ) -> List[dict]:
        """Process tool calls and append results to messages."""
        updated_messages = messages.copy()

        for tool_call in tool_calls:
            try:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)

                if function_name in tools_functions:
                    result = await tools_functions[function_name](**function_args)

                    updated_messages.extend(
                        [
                            {
                                "role": MessageRole.tool,
                                "content": json.dumps(tool_call.function),
                            },
                            {
                                "role": MessageRole.tool,
                                "content": json.dumps(result),
                            },
                        ]
                    )

            except Exception as e:
                self.logger.error(f"Error processing tool call: {str(e)}")

        return updated_messages

    async def generate_response(
        self,
        user: User,
        message: str,
    ) -> Optional[str]:
        """Generate a response, handling message batching and tool calls."""
        processor = self._get_processor(user.id)
        processor.add_message(message)

        self.logger.info(
            f"Message buffer for user: {user.wa_id}, buffer: {processor.get_pending_messages()}"
        )

        if processor.is_locked:
            self.logger.info(f"Lock held for user {user.id}, message buffered")
            return None

        message_history = await get_user_message_history(user.id)
        formatted_messages = self._format_conversation_history(message_history)

        async with processor.lock:
            while True:
                try:
                    messages_to_process = processor.get_pending_messages()

                    if not messages_to_process:  # Shouldn't happen, but just in case
                        processor.clear_messages()
                        self._cleanup_processor(user.id)
                        return None

                    # TODO: handle the fact that the messages_to_process and database formatted_messages have an overlap
                    # Prepare messages for API
                    api_messages = [
                        *formatted_messages,
                        {"role": "user", "content": "\n".join(messages_to_process)},
                    ]

                    # Initial generation with tools enabled
                    initial_response = await self._generate_completion(
                        api_messages, include_tools=True
                    )
                    if not initial_response:
                        return None

                    # Check for new messages
                    if await self._check_new_messages(
                        processor, len(messages_to_process)
                    ):
                        self.logger.info(
                            "New messages arrived during processing, restarting"
                        )
                        continue

                    # Process tool calls if present
                    if initial_response.tool_calls:
                        # TODO: Tool calls should be written to the database when they are made and actually used
                        updated_messages = await self._process_tool_calls(
                            api_messages, initial_response.tool_calls
                        )

                        # Generate final response with tool results
                        # TODO: This should allow for loops of tool calls to be made if the initial tool call didn't satisfy the LLM
                        final_response = await self._generate_completion(
                            updated_messages
                        )
                        if not final_response:
                            return None

                        # Check for new messages again
                        if await self._check_new_messages(
                            processor, len(messages_to_process)
                        ):
                            continue

                        response_content = final_response.content
                    else:
                        response_content = initial_response.content

                    # Success - clear buffer and return response
                    processor.clear_messages()
                    self._cleanup_processor(user.id)
                    return response_content

                except Exception as e:
                    self.logger.error(f"Error processing messages: {e}")
                    # On error, preserve messages and clean up
                    self._cleanup_user(user.id)
                    return None

    async def _handle_tool_calls(
        self, messages: List[dict], tool_calls: List[Any]
    ) -> List[dict]:
        """Handle tool calls and append results to messages."""
        updated_messages = messages.copy()

        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)

            if function_name in tools_functions:
                try:
                    function_response = await tools_functions[function_name](
                        **function_args
                    )

                    # Add the tool response to messages
                    updated_messages.append(
                        {
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": json.dumps(function_response),
                        }
                    )
                except Exception as e:
                    self.logger.error(f"Error calling tool {function_name}: {e}")
                    # Add error response to messages
                    updated_messages.append(
                        {
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": json.dumps({"error": str(e)}),
                        }
                    )

        return updated_messages

    def _format_conversation_history(
        self, messages: Optional[List[Message]]
    ) -> List[dict]:
        # TODO: Handle message history using eg. sliding window, truncation, vector database, summarization
        formatted_messages = []

        # Add system message at the start
        system_prompt = get_system_prompt("default_system")

        # Add system message (this is not stored in the database to allow for updates)
        formatted_messages.append({"role": "system", "content": system_prompt})

        # Format each message from the history
        if messages:
            for msg in messages:
                formatted_messages.append({"role": msg.role, "content": msg.content})

        return formatted_messages


llm_client = LLMClient()
