import json
import uuid
from typing import Optional
from langchain_core.messages import AIMessage, HumanMessage
from app.database.models import Message, User
from app.database.enums import MessageRole
from app.config import settings, llm_settings, LLMProvider
from app.utils.llm_utils import async_llm_request
from app.utils.string_manager import strings, StringCategory
from app.services.client_base import ClientBase


def _prepare_message_for_together(message: AIMessage) -> HumanMessage | AIMessage:
    """Ensure Together receives tool calls with stringified arguments and correct role."""
    content = message.content if message.content is not None else ""
    raw_tool_calls = getattr(message, "tool_calls", None)

    if not raw_tool_calls:
        return message if content == message.content else AIMessage(content=content)

    sanitized_tool_calls = []
    for call in raw_tool_calls:
        if hasattr(call, "model_dump"):
            call_dict = call.model_dump()
        elif isinstance(call, dict):
            call_dict = dict(call)
        else:
            call_dict = json.loads(json.dumps(call))

        function = call_dict.get("function", {})
        name = call_dict.get("name") or function.get("name", "")
        arguments = (
            function.get("arguments")
            if function.get("arguments") is not None
            else call_dict.get("arguments")
        )
        if arguments is None:
            arguments = call_dict.get("args", {})
        if not isinstance(arguments, str):
            try:
                arguments = json.dumps(arguments)
            except TypeError:
                arguments = json.dumps(str(arguments))

        sanitized_tool_calls.append(
            {
                "id": call_dict.get("id") or f"call_{uuid.uuid4()}",
                "type": call_dict.get("type", "function"),
                "function": {"name": name, "arguments": arguments},
            }
        )

    additional_kwargs = dict(message.additional_kwargs or {})
    additional_kwargs["tool_calls"] = sanitized_tool_calls

    return HumanMessage(content=content, additional_kwargs=additional_kwargs)


class LLMClient(ClientBase):
    def __init__(self) -> None:
        super().__init__()

    async def generate_response(
        self,
        user: User,
        message: Message,
    ) -> Optional[list[Message]]:
        """Generate a response, handling message batching and tool calls."""
        assert user.id is not None
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
                        return None  # cleanup in finally

                    # 1. Build the API messages from DB history + new messages
                    api_messages = await self._build_api_messages(
                        user, messages_to_process
                    )

                    # Check the length of the messages, make sure it does not exceed character limit
                    message_lengths = [
                        0 if msg.content is None else len(msg.content)
                        for msg in api_messages
                    ]
                    self.logger.debug(
                        f"Total number of characters in user API messages: {sum(message_lengths)}"
                    )

                    # TODO: Issue #92: Optimizing chat history usage & context window input
                    if message_lengths[-1] > settings.message_character_limit:
                        self.logger.error(
                            f"User {user.wa_id}: {strings.get_string(StringCategory.ERROR, 'character_limit_exceeded')}"
                        )
                        return [
                            Message(
                                user_id=user.id,
                                role=MessageRole.system,
                                content=strings.get_string(
                                    StringCategory.ERROR, "character_limit_exceeded"
                                ),
                            )
                        ]

                    # 2. Call the LLM with tools enabled
                    self.logger.debug("Initiating LLM request")
                    initial_response = await async_llm_request(
                        messages=api_messages,
                        tools=self.tool_manager.get_tools_metadata_from_registry(
                            available_classes=json.dumps(user.class_name_to_id_map)
                        ),
                        tool_choice="auto",
                        verbose=False,
                        run_name=f"twiga_initial_chat_{user.wa_id}",
                        metadata={
                            "user_id": str(user.id),
                            "user_wa_id": user.wa_id,
                            "user_name": user.name,
                            "message_count": len(api_messages),
                            "phase": "initial_request",
                        },
                    )

                    self.logger.debug(f"LLM response:\n {initial_response.content}")
                    self.logger.debug("Formatting LLM response")

                    # Create message from LangChain AIMessage directly
                    initial_message = self._llm_response_to_message(
                        llm_response=initial_response, user_id=user.id
                    )

                    tool_calls = self.tool_manager.extract_tool_calls(initial_response)
                    if tool_calls:
                        initial_message.tool_calls = tool_calls
                        initial_message.content = None

                    # Track new messages
                    new_messages = [initial_message]

                    if self._check_new_messages(processor, original_count):
                        self.logger.warning("New messages buffered during processing")
                        continue

                    # 5. Process tool calls if present (whether normal or recovered)
                    if initial_message.tool_calls:
                        self.logger.debug("Processing tool calls 🛠️")
                        self.logger.debug(f"Tool calls: {initial_message.tool_calls}")

                        # Send notifications for all unique tools upfront
                        unique_tools = {
                            tool_call["function"]["name"]
                            for tool_call in initial_message.tool_calls
                        }
                        for tool_name in unique_tools:
                            await self._tool_call_notification(user, tool_name)

                        # Process tool calls and track the tool response messages
                        tool_responses = await self.tool_manager.process_tool_calls(
                            initial_message.tool_calls,
                            user,
                        )

                        if tool_responses:
                            new_messages.extend(tool_responses)

                            # Add the AI message with tool calls to api_messages, then add tool responses to keep the message order in history
                            assistant_message = initial_response
                            if (
                                llm_settings.provider == LLMProvider.TOGETHER
                                and isinstance(initial_response, AIMessage)
                            ):
                                assistant_message = _prepare_message_for_together(
                                    initial_response
                                )

                            api_messages.append(assistant_message)
                            api_messages.extend(
                                msg.to_langchain_message() for msg in tool_responses
                            )

                            # 6. Final call to LLM with the new tool outputs appended
                            final_response = await async_llm_request(
                                messages=api_messages,
                                tools=None,
                                tool_choice=None,
                                run_name=f"twiga_final_chat_{user.wa_id}",
                                metadata={
                                    "user_id": str(user.id),
                                    "user_wa_id": user.wa_id,
                                    "user_name": user.name,
                                    "message_count": len(api_messages),
                                    "phase": "final_request_with_tools",
                                    "tool_calls_processed": len(tool_responses),
                                },
                            )
                            final_message = Message.from_langchain_message(
                                final_response, user.id
                            )
                            new_messages.append(final_message)

                        # Check for new messages again
                        if self._check_new_messages(processor, original_count):
                            self.logger.warning("New messages buffered during tools")
                            continue

                    # 7. If we got this far, we return the messages
                    self.logger.debug("LLM finished.")
                    self.logger.debug(f"New messages: {new_messages}")
                    return new_messages

                except Exception as e:
                    self.logger.error(f"Error processing messages: {e}")
                    return None
                finally:
                    # This always runs, whether we returned above or an exception occurred.
                    self.logger.debug(
                        "Clearing message buffer and cleaning up processor"
                    )
                    processor.clear_messages()
                    self._cleanup_processor(user.id)


llm_client = LLMClient()
