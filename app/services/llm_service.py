import re
import json
import logging
import asyncio
from typing import List, Optional
from openai.types.chat import ChatCompletionMessageToolCall

from app.database.models import Message, User
from app.database.enums import MessageRole
from app.config import llm_settings
from app.database.db import get_user_message_history
from app.utils.llm_utils import async_llm_request
from app.utils.prompt_manager import prompt_manager
from app.tools.registry import tools_functions, tools_metadata


class MessageProcessor:
    """Handles processing and batching of messages for a single user."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.lock = asyncio.Lock()
        self.messages: List[Message] = []

    def add_message(self, message: Message) -> None:
        self.messages.append(message)

    def get_pending_messages(self) -> List[Message]:
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
        self.logger = logging.getLogger(__name__)
        self._processors: dict[int, MessageProcessor] = {}

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

    def _catch_malformed_tool(self, response_text: str) -> str | dict:
        """
        Parse response text to extract a tool call if present.

        Expected format:
            <function=FUNCTION_NAME>{ ... valid JSON ... }</function>

        Returns:
            - dict: if the tool call is successfully parsed, for example:
                    {
                        "name": "FUNCTION_NAME",
                        "arguments": { ...parsed JSON... }
                    }
            - str: if no valid tool call is found or parsing fails (we return original text).
        """
        # This regex looks for any string that matches <function=FUNCTION_NAME> ... </function>
        # where FUNCTION_NAME can be letters/underscores followed by any word characters.
        pattern = r"<function=([A-Za-z_]\w*)>(.*?)</function>"
        match = re.search(pattern, response_text, flags=re.DOTALL)

        # If there's no match for <function=...>...</function>, just return the original text
        if not match:
            return response_text

        function_name = match.group(1)
        json_str = match.group(2).strip()
        json_str = json_str.rstrip('"').strip()

        try:
            parsed_arguments = json.loads(json_str)
        except json.JSONDecodeError:
            # If parsing fails, we return the original text or handle it differently
            return response_text

        # Return a structured dict so upstream code knows it was a valid tool call
        return {"name": function_name, "arguments": parsed_arguments}

    async def _process_tool_calls(
        self,
        tool_calls: List[ChatCompletionMessageToolCall],
        user: User,
        resources: Optional[List[int]] = None,
    ) -> Optional[List[Message]]:
        """Process tool calls and return just the new tool response messages."""
        if not resources:
            self.logger.error("No resources available for tool calls")
            return [
                Message(
                    user_id=user.id,
                    role=MessageRole.system,
                    content=json.dumps(
                        {
                            "error": "Tools are not available right now, no available resources."
                        }
                    ),
                )
            ]

        tool_responses = []
        for tool_call in tool_calls:
            try:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                # TODO: Make this more modular, depending on the need for each tool
                function_args["user"] = user
                function_args["resources"] = resources

                if function_name in tools_functions:
                    tool_func = tools_functions[function_name]
                    result = (
                        await tool_func(**function_args)
                        if asyncio.iscoroutinefunction(tool_func)
                        else tool_func(**function_args)
                    )

                    tool_responses.append(
                        Message(
                            user_id=user.id,
                            role=MessageRole.tool,
                            content=json.dumps(result),
                            tool_call_id=tool_call.id,
                        )
                    )
            except Exception as e:
                self.logger.error(f"Error in {function_name}: {str(e)}")
                tool_responses.append(
                    Message(
                        user_id=user.id,
                        role=MessageRole.tool,
                        content=json.dumps({"error": str(e)}),
                        tool_call_id=tool_call.id,
                    )
                )

            return tool_responses

    async def generate_response(
        self,
        user: User,
        message: Message,
        resources: Optional[List[int]] = None,
    ) -> Optional[List[Message]]:
        """Generate a response, handling message batching and tool calls."""
        processor = self._get_processor(user.id)
        processor.add_message(message)

        self.logger.debug(
            f"Message buffer for user: {user.wa_id}, buffer: {processor.get_pending_messages()}"
        )

        if processor.is_locked:
            self.logger.info(f"Lock held for user {user.wa_id}, message buffered")
            return None

        async with processor.lock:
            while True:
                try:
                    messages_to_process = processor.get_pending_messages()
                    original_count = len(messages_to_process)
                    if not messages_to_process:
                        self.logger.warning(f"No messages to process for {user.wa_id}.")
                        processor.clear_messages()
                        self._cleanup_processor(user.id)
                        return None

                    # 1. Build the API messages from DB history + new messages
                    history = await get_user_message_history(user.id)
                    api_messages = self._format_messages(
                        messages_to_process, history, user
                    )
                    self.logger.debug(f"Initial messages:\n {api_messages}")

                    # 2. Call the LLM with tools enabled
                    initial_response = await async_llm_request(
                        model=llm_settings.llm_model_name,
                        messages=api_messages,
                        tools=tools_metadata,
                        tool_choice="auto",
                    )
                    initial_message = Message.from_api_format(
                        initial_response.choices[0].message.model_dump(), user.id
                    )
                    self.logger.debug(f"LLM response:\n {initial_message}")

                    # Track new messages
                    new_messages = [initial_message]

                    # 3. Check for new incoming messages during processing
                    if self._check_new_messages(processor, original_count):
                        self.logger.warning("New messages buffered during processing")
                        continue

                    # 4. If the LLM didn't return a standard tool call but we suspect there's a call in content
                    if not initial_message.tool_calls:
                        self.logger.debug(
                            "No tool calls in the standard field. Checking for malformed calls."
                        )
                        # Attempt to parse a malformed/hallucinated tool call
                        tool_call_data = self._catch_malformed_tool(
                            initial_message.content
                        )
                        self.logger.debug(f"Recovered tool call data: {tool_call_data}")
                        if tool_call_data is not None and isinstance(
                            tool_call_data, dict
                        ):
                            self.logger.warning(
                                "Recovered a malformed/hallucinated tool call from content."
                            )
                            # Rebuild the tool call
                            from openai.types.chat import ChatCompletionMessageToolCall

                            recovered_call = ChatCompletionMessageToolCall(
                                id="recovered_call_1",
                                function=ChatCompletionMessageToolCall.Function(
                                    name=tool_call_data["name"],
                                    arguments=json.dumps(
                                        tool_call_data["arguments"]["query"]
                                    ),
                                ),
                                type="function",
                            )
                            # Assign it back to the message so _process_tool_calls will see it
                            initial_message.tool_calls = [recovered_call]
                        else:
                            self.logger.debug(
                                "No malformed tool call found in content."
                            )

                    # 5. Process tool calls if present (whether normal or recovered)
                    if initial_message.tool_calls:
                        self.logger.debug("Processing tool calls 🛠️")
                        tool_responses = await self._process_tool_calls(
                            initial_message.tool_calls,  # note: we can also do initial_response.choices[0].message.tool_calls
                            user,
                            resources,
                        )

                        if tool_responses:
                            new_messages.extend(tool_responses)
                            # Extend api_messages with new tool responses
                            api_messages.extend(
                                msg.to_api_format() for msg in tool_responses
                            )

                            # 6. Final call to LLM with the new tool outputs appended
                            final_response = await async_llm_request(
                                model=llm_settings.llm_model_name,
                                messages=api_messages,
                                tools=None,
                                tool_choice=None,
                            )
                            final_message = Message.from_api_format(
                                final_response.choices[0].message.model_dump(), user.id
                            )
                            new_messages.append(final_message)

                        # Check for new messages again
                        if self._check_new_messages(processor, original_count):
                            self.logger.warning("New messages buffered during tools")
                            continue

                    # 7. If we got this far, we can clear the buffer and return
                    self.logger.debug("LLM finished. Clearing buffer.")
                    processor.clear_messages()
                    self._cleanup_processor(user.id)
                    return new_messages

                except Exception as e:
                    self.logger.error(f"Error processing messages: {e}")
                    processor.clear_messages()
                    self._cleanup_processor(user.id)
                    return None

    @staticmethod
    def _format_messages(
        new_messages: List[Message],
        database_messages: List[Message],
        user: User,
    ) -> List[dict]:
        """
        Format messages for the API, removing duplicates between new messages and database history.
        """
        # Initialize with system prompt
        formatted_messages = [
            {
                "role": MessageRole.system,
                "content": prompt_manager.format_prompt(
                    "twiga_system", user_name=user.name, class_info=user.class_info
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


llm_client = LLMClient()
