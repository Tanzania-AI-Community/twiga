import json
import logging
from typing import Optional, List
from langchain_core.messages import AIMessage
from app.database.models import Message, User
from app.services.client_base import ClientBase
from app.utils.enums import Prompt
from app.utils.llm_utils import async_llm_request
from app.database.enums import MessageRole
from app.utils.string_manager import strings, StringCategory
from app.config import llm_settings
from app.config import settings


class AgentClient(ClientBase):
    """
    A client that uses an agentic, iterative approach to generate responses.
    The agent can think, act (call tools), and observe in a loop.
    """

    def __init__(self) -> None:
        super().__init__()
        self.logger = logging.getLogger(__name__)

    async def generate_response(
        self,
        user: User,
        message: Message,
    ) -> Optional[List[Message]]:
        """Generates a response using an agentic loop."""
        if user.id is None:
            self.logger.error("User object is missing an ID, cannot generate response.")
            raise ValueError("User object must have an ID to generate a response.")

        processor = self._get_processor(user.id)
        processor.add_message(message)

        self.logger.debug(
            f"Message buffer for user: {user.id}, buffer: {processor.get_pending_messages()}"
        )

        if processor.is_locked:
            self.logger.info(f"Lock held for user {user.id}, message buffered")
            return None

        async with processor.lock:
            while True:
                try:
                    messages_to_process = processor.get_pending_messages()
                    original_count = len(messages_to_process)
                    if not messages_to_process:
                        self.logger.warning(
                            f"No messages to process for user.id={user.id}."
                        )
                        return None

                    api_messages = await self._build_api_messages(
                        user=user,
                        messages_to_process=messages_to_process,
                        prompt=Prompt.TWIGA_AGENT_SYSTEM,
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

                    """
                    Basic Agentic approach, run until no more tools are called
                    """
                    final_messages: List[Message] = []
                    for i in range(llm_settings.MAX_AGENT_ITERATIONS):
                        self.logger.debug(
                            f"Agent iteration {i + 1}/{llm_settings.MAX_AGENT_ITERATIONS}"
                        )

                        # 1. THINK/ACT: Call the LLM with tools
                        self.logger.debug("Initiating LLM request")
                        llm_response: AIMessage = await async_llm_request(
                            messages=api_messages,
                            tools=self.tool_manager.get_tools_metadata_from_registry(
                                available_classes=json.dumps(user.class_name_to_id_map)
                            ),
                            tool_choice="auto",
                            verbose=False,
                            run_name=f"twiga_initial_chat_{user.id}",
                            metadata={
                                "user_id": str(user.id),
                                "message_count": len(api_messages),
                                "phase": f"agent_loop_{i + 1}/{llm_settings.MAX_AGENT_ITERATIONS}",
                            },
                        )

                        response_message = self._llm_response_to_message(
                            llm_response=llm_response, user_id=user.id
                        )

                        self.logger.debug(
                            f"LLM Response (AGENT LOOP): {llm_response.content}"
                        )

                        tool_calls = self.tool_manager.extract_tool_calls(llm_response)
                        if not tool_calls:
                            # No tool calls, this is the final answer
                            self.logger.info("Agent finished: No tool calls detected.")
                            final_messages.append(response_message)
                            break

                        # 2. OBSERVE: Tools were called, process them
                        self.logger.info(
                            f"Agent action: processing {len(tool_calls)} tool call(s)."
                        )
                        self.logger.debug(f"Tool calls: {tool_calls}")

                        response_message.tool_calls = tool_calls
                        response_message.content = (
                            None  # Content is empty for tool calls
                        )
                        final_messages.append(response_message)

                        # Send notifications for all unique tools upfront
                        unique_tools = {
                            tool_call["function"]["name"] for tool_call in tool_calls
                        }
                        for tool_name in unique_tools:
                            await self._tool_call_notification(user, tool_name)

                        # Process tool calls and track the tool response messages
                        tool_responses = await self.tool_manager.process_tool_calls(
                            tool_calls, user
                        )
                        if tool_responses:
                            final_messages.extend(tool_responses)

                            # Append the agent's tool request and the tool's output to the history
                            api_messages.append(llm_response)
                            api_messages.extend(
                                [msg.to_langchain_message() for msg in tool_responses]
                            )
                    else:
                        # Max iterations reached, force a final response
                        self.logger.warning(
                            f"Max iterations ({llm_settings.MAX_AGENT_ITERATIONS}) reached. Forcing final response."
                        )
                        final_llm_response = await async_llm_request(
                            messages=api_messages,
                            tools=None,
                            tool_choice=None,
                            run_name=f"twiga_final_chat_{user.id}",
                            metadata={
                                "user_id": str(user.id),
                                "message_count": len(api_messages),
                                "phase": "agent_forced_final_request",
                            },
                        )

                        final_messages.append(
                            self._llm_response_to_message(final_llm_response, user.id)
                        )

                    # Before returning, check if new messages arrived during processing
                    if self._check_new_messages(processor, original_count):
                        self.logger.warning("New messages buffered during processing")
                        continue

                    return final_messages
                except Exception as e:
                    self.logger.error(f"Error processing messages in agent loop: {e}")
                    return None
                finally:
                    # This always runs, whether we returned above or an exception occurred.
                    self.logger.debug(
                        "Clearing message buffer and cleaning up processor"
                    )
                    processor.clear_messages()
                    self._cleanup_processor(user.id)


agent_client = AgentClient()
