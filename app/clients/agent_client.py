import json
import logging
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

import app.database.db as db
from app.clients.agent_modes import (
    AgentMode,
    AgentModeConfig,
    get_mode_config,
    resolve_agent_mode,
)
from app.clients.client_base import (
    BUFFERED_RESPONSE,
    ClientBase,
    GenerateResponseResult,
    Preparation,
    PreparationFailed,
)
from app.config import llm_settings
from app.database.models import Message, User
from app.services.profile import Catalog, available_catalog
from app.tools.registry import PROFILE_TOOLS, ToolName
from app.utils.llm_utils import async_llm_request
from app.utils.prompt_manager import prompt_manager


@dataclass(frozen=True)
class TurnTools:
    """What the model may use during one turn."""

    config: AgentModeConfig
    allowed: frozenset[ToolName]
    catalog: Catalog | None


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
        turn: TurnTools,
    ) -> AIMessage:
        """
        THINK: Call the LLM with tools to generate next response or tool calls.

        Args:
            api_messages: Current conversation history
            user: User object for context
            iteration: Current iteration number
            turn: Mode, allowed tools and catalog for this turn

        Returns:
            AIMessage from the LLM
        """
        return await async_llm_request(
            messages=api_messages,
            tools=self.tool_manager.get_tools_metadata_from_registry(
                available_classes=json.dumps(user.class_name_to_id_map),
                allowed=turn.allowed,
                catalog=turn.catalog,
            ),
            tool_choice="auto",
            verbose=False,
            run_name=f"twiga_initial_chat_{user.id}",
            metadata={
                "user_id": str(user.id),
                "message_count": len(api_messages),
                "phase": f"agent_loop_{iteration + 1}/{llm_settings.MAX_AGENT_ITERATIONS}",
                "mode": turn.config.mode.value,
                **prompt_manager.build_trace_metadata(
                    system_prompt_name=turn.config.prompt.value
                ),
            },
        )

    async def _observe(
        self,
        tool_calls: list[dict],
        user: User,
        api_messages: list,
        final_messages: list[Message],
        notified_tools: set[str],
        turn: TurnTools,
    ) -> list[Message]:
        """
        OBSERVE: Process tool calls and collect their responses.

        Args:
            tool_calls: List of tool calls to process
            user: User object for context
            api_messages: Current conversation history (will be modified)
            final_messages: List of final messages (will be modified)
            notified_tools: Tools already announced to the user this turn (will be modified)
            turn: Mode, allowed tools and catalog for this turn

        Returns:
            List of tool response messages
        """
        self.logger.info(f"Agent action: processing {len(tool_calls)} tool call(s).")
        self.logger.debug(f"Tool calls: {tool_calls}")

        unique_tools = {tool_call["function"]["name"] for tool_call in tool_calls}
        for tool_name in sorted(unique_tools - notified_tools):
            await self._tool_call_notification(user, tool_name)
        notified_tools.update(unique_tools)

        tool_responses = await self.tool_manager.process_tool_calls(
            tool_calls, user, allowed=turn.allowed
        )
        return tool_responses

    async def _force_final(
        self,
        api_messages: list,
        user: User,
        turn: TurnTools,
    ) -> Message:
        """
        Force a final response when max iterations reached.

        Args:
            api_messages: Current conversation history
            user: User object for context
            turn: Mode, allowed tools and catalog for this turn

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
                "mode": turn.config.mode.value,
                **prompt_manager.build_trace_metadata(
                    system_prompt_name=turn.config.prompt.value
                ),
            },
        )

        return self._llm_response_to_message(final_llm_response, user.id)

    async def _load_turn_tools(self, config: AgentModeConfig) -> TurnTools:
        """Resolve the tools for this turn; profile tools need the catalog."""
        if not config.tools & PROFILE_TOOLS:
            return TurnTools(config=config, allowed=config.tools, catalog=None)
        try:
            catalog = await available_catalog()
        except Exception as e:
            # Teaching help must keep working even if the catalog cannot load
            self.logger.warning(
                "Subject catalog unavailable, profile tools disabled this turn: %s",
                type(e).__name__,
            )
            return TurnTools(
                config=config, allowed=config.tools - PROFILE_TOOLS, catalog=None
            )
        return TurnTools(config=config, allowed=config.tools, catalog=catalog)

    async def _refresh_context(
        self, user: User, api_messages: list[BaseMessage], config: AgentModeConfig
    ) -> User:
        """After a profile change, reload the teacher and re-render the system prompt.

        Without this the rest of the turn would see the old name and classes, and
        the class IDs offered to the curriculum tools would be stale.
        """
        try:
            fresh_user = await db.get_user_by_waid(user.wa_id)
        except Exception as e:
            # The profile is already saved; only this turn's context stays stale
            self.logger.warning(
                "Could not refresh the agent context: %s", type(e).__name__
            )
            return user
        if fresh_user is None:
            self.logger.warning("User disappeared while refreshing the agent context.")
            return user
        api_messages[0] = SystemMessage(
            content=self._render_system_prompt(
                fresh_user, config.prompt, config.prompt_variables(fresh_user)
            )
        )
        return fresh_user

    @staticmethod
    def _changed_profile(tool_calls: list[dict]) -> bool:
        profile_tool_names = {tool.value for tool in PROFILE_TOOLS}
        return any(
            tool_call["function"]["name"] in profile_tool_names
            for tool_call in tool_calls
        )

    async def generate_response(
        self,
        user: User,
        message: Message,
        prepare: Preparation | None = None,
        mode: AgentMode | None = None,
    ) -> GenerateResponseResult:
        """Generates a response using an agentic loop.

        `prepare` readies the message under the user's turn, so messages arriving
        meanwhile are answered with it instead of overtaking it. `mode` defaults
        to the one implied by the user's state.
        """
        if user.id is None:
            self.logger.error("User object is missing an ID, cannot generate response.")
            raise ValueError("User object must have an ID to generate a response.")

        if prepare and self._get_processor(user.id).is_locked:
            # The running turn would otherwise answer this message unprepared
            if error_key := await prepare():
                return PreparationFailed(error_key)
            prepare = None

        # Fetched again: the running turn may have finished and removed it
        processor = self._get_processor(user.id)
        processor.add_message(message)

        self.logger.debug(
            f"Message buffer for user: {user.id}, buffer: {processor.get_pending_messages()}"
        )

        if processor.is_locked:
            self.logger.info(f"Lock held for user {user.id}, message buffered")
            return BUFFERED_RESPONSE

        try:
            async with processor.lock:
                config = get_mode_config(mode or resolve_agent_mode(user))
                # A tool is announced at most once per turn
                notified_tools: set[str] = set()
                try:
                    if prepare and (error_key := await prepare()):
                        self.logger.info(
                            f"Preparation failed for user {user.id}: {error_key}"
                        )
                        processor.remove([message])
                        if not processor.has_messages:
                            return PreparationFailed(error_key)
                        # Messages buffered during preparation are still answered

                    while True:
                        api_messages, error_messages = await self._preprocess_messages(
                            user=user,
                            processor=processor,
                            prompt=config.prompt,
                            prompt_variables=config.prompt_variables(user),
                        )

                        if error_messages:
                            return error_messages
                        if api_messages is None:
                            return None

                        turn = await self._load_turn_tools(config)

                        # Track original message count for new message detection
                        original_count = len(processor.get_pending_messages())

                        """
                        Basic Agentic approach, run until no more tools are called
                        """
                        final_messages: list[Message] = []
                        for iteration in range(llm_settings.MAX_AGENT_ITERATIONS):
                            self.logger.debug(
                                f"Agent iteration {iteration + 1}/{llm_settings.MAX_AGENT_ITERATIONS}"
                            )

                            # 1. THINK: Call the LLM with tools
                            llm_response = await self._think(
                                api_messages=api_messages,
                                user=user,
                                iteration=iteration,
                                turn=turn,
                            )
                            response_message = self._llm_response_to_message(
                                llm_response=llm_response, user_id=user.id
                            )

                            self.logger.debug(f"LLM Response: {llm_response.content}")

                            tool_calls = self.tool_manager.extract_tool_calls(
                                llm_response
                            )
                            if not tool_calls:
                                self.logger.info(
                                    "Agent finished: No tool calls detected."
                                )
                                final_messages.append(response_message)
                                break

                            # 2. ACT: Record that we're calling tools
                            response_message.tool_calls = tool_calls
                            response_message.content = None
                            final_messages.append(response_message)

                            # 3. OBSERVE: Execute tools and get responses
                            tool_responses = await self._observe(
                                tool_calls=tool_calls,
                                user=user,
                                api_messages=api_messages,
                                final_messages=final_messages,
                                notified_tools=notified_tools,
                                turn=turn,
                            )

                            if tool_responses:
                                final_messages.extend(tool_responses)

                                # Append the agent's tool request and the tool's output to the history
                                api_messages.append(llm_response)
                                api_messages.extend(
                                    [
                                        msg.to_langchain_message()
                                        for msg in tool_responses
                                    ]
                                )

                            if self._changed_profile(tool_calls):
                                user = await self._refresh_context(
                                    user, api_messages, config
                                )
                        else:
                            # Max iterations reached, force a final response (does not run if break is hit)
                            final_message = await self._force_final(
                                api_messages, user, turn
                            )
                            final_messages.append(final_message)

                        if self._check_new_messages(processor, original_count):
                            self.logger.info(
                                "New messages buffered during processing. Discarding response and reprocessing batch."
                            )
                            continue

                        # the last message in final messages is always an assistant message (either from normal
                        # flow or forced final), so we can assign source_chunk_ids there
                        if final_messages:
                            final_messages[-1].source_chunk_ids = (
                                self._get_source_chunk_ids(final_messages) or None
                            )

                        return final_messages
                except Exception as e:
                    self.logger.error(f"Error processing messages in agent loop: {e}")
                    return None
                finally:
                    # This always runs, whether we returned above or an exception occurred.
                    self.logger.debug("Clearing message buffer")
                    processor.clear_messages()
        finally:
            # Outside the lock: an idle processor can only be removed once released
            self._cleanup_processor(user.id)


agent_client = AgentClient()
