import json
import logging
from typing import Optional
from langchain_core.messages import AIMessage
from app.database.models import Message, User
from app.services.client_base import ClientBase
from app.utils.llm_utils import async_llm_request
from app.config import llm_settings, Prompt


class AgentClient(ClientBase):
    """
    A client that uses an agentic, iterative approach to generate responses.
    The agent can think, act (call tools), and observe in a loop.
    """

    def __init__(self) -> None:
        super().__init__()
        self.logger = logging.getLogger(__name__)

    async def _think(
        self,
        api_messages: list,
        user: User,
        iteration: int,
    ) -> AIMessage:
        """
        THINK: Call the LLM with tools to generate next response or tool calls.

        Args:
            api_messages: Current conversation history
            user: User object for context
            iteration: Current iteration number

        Returns:
            AIMessage from the LLM
        """
        self.logger.debug("Initiating LLM request")
        return await async_llm_request(
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
                "phase": f"agent_loop_{iteration + 1}/{llm_settings.MAX_AGENT_ITERATIONS}",
            },
        )

    async def _observe(
        self,
        tool_calls: list[dict],
        user: User,
        api_messages: list,
        final_messages: list[Message],
    ) -> list[Message]:
        """
        OBSERVE: Process tool calls and collect their responses.

        Args:
            tool_calls: List of tool calls to process
            user: User object for context
            api_messages: Current conversation history (will be modified)
            final_messages: List of final messages (will be modified)

        Returns:
            List of tool response messages
        """
        self.logger.info(f"Agent action: processing {len(tool_calls)} tool call(s).")
        self.logger.debug(f"Tool calls: {tool_calls}")

        # Send notifications for all unique tools upfront
        unique_tools = {tool_call["function"]["name"] for tool_call in tool_calls}
        for tool_name in unique_tools:
            await self._tool_call_notification(user, tool_name)

        # Process tool calls and track the tool response messages
        tool_responses = await self.tool_manager.process_tool_calls(tool_calls, user)

        return tool_responses

    async def _force_final(
        self,
        api_messages: list,
        user: User,
    ) -> Message:
        """
        Force a final response when max iterations reached.

        Args:
            api_messages: Current conversation history
            user: User object for context

        Returns:
            Final message from the LLM
        """
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

        return self._llm_response_to_message(final_llm_response, user.id)

    async def generate_response(
        self,
        user: User,
        message: Message,
    ) -> Optional[list[Message]]:
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
                    # Preprocess messages: validate and build API messages
                    api_messages, error_messages = await self._preprocess_messages(
                        user=user,
                        processor=processor,
                        prompt=Prompt.TWIGA_AGENT_SYSTEM,
                    )

                    # Return early if validation failed or no messages
                    if error_messages:
                        return error_messages
                    if api_messages is None:
                        return None

                    # Track original message count for new message detection
                    original_count = len(processor.get_pending_messages())

                    """
                    Basic Agentic approach, run until no more tools are called
                    """
                    final_messages: list[Message] = []
                    for i in range(llm_settings.MAX_AGENT_ITERATIONS):
                        self.logger.debug(
                            f"Agent iteration {i + 1}/{llm_settings.MAX_AGENT_ITERATIONS}"
                        )

                        # 1. THINK: Call the LLM with tools
                        llm_response = await self._think(api_messages, user, i)

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

                        # 2. ACT: Record that we're calling tools
                        response_message.tool_calls = tool_calls
                        response_message.content = (
                            None  # Content is empty for tool calls
                        )
                        final_messages.append(response_message)

                        # 3. OBSERVE: Execute tools and get responses
                        tool_responses = await self._observe(
                            tool_calls, user, api_messages, final_messages
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
                        final_message = await self._force_final(api_messages, user)
                        final_messages.append(final_message)

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
