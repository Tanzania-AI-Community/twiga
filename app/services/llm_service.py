import json
import logging
import asyncio
from typing import Any, Callable, List, Optional, Tuple
from together import AsyncTogether


from app.database.models import Message, User
from app.utils.whatsapp_utils import get_text_payload
from app.config import llm_settings
from app.database.db import get_user_message_history
from app.services.whatsapp_service import whatsapp_client
from assets.prompts import get_system_prompt


# from app.tools.exercise.executor import generate_exercise


class LLMClient:
    def __init__(self):
        self.client = AsyncTogether(
            api_key=llm_settings.together_api_key.get_secret_value(),
        )
        self.logger = logging.getLogger(__name__)
        self._user_locks = {}  # {user_id: Lock()}
        self._message_buffers = {}  # {user_id: ["message1", "message2"]}

    def _get_user_lock(self, user_id: int) -> asyncio.Lock:
        """Get or create a lock for a specific user."""
        if user_id not in self._user_locks:
            self._user_locks[user_id] = asyncio.Lock()
        return self._user_locks[user_id]

    def _get_message_buffer(self, user_id: int) -> list:
        """Get or create a message buffer for a specific user."""
        if user_id not in self._message_buffers:
            self._message_buffers[user_id] = []
        return self._message_buffers[user_id]

    def _cleanup_user(self, user_id: int):
        """Remove user's lock and buffer if they're empty."""
        if user_id in self._message_buffers and not self._message_buffers[user_id]:
            del self._message_buffers[user_id]
        if user_id in self._user_locks and not self._user_locks[user_id].locked():
            del self._user_locks[user_id]

    async def generate_response(
        self, user: User, message: str, verbose: bool = False
    ) -> Optional[str]:
        """Generate a response, restarting if new messages arrive during processing."""
        user_lock = self._get_user_lock(user.id)
        message_buffer = self._get_message_buffer(user.id)

        # Add message to buffer (this updates self._message_buffers[user.id] since they refer to the same object in memory)
        message_buffer.append(message)

        self.logger.info(f"Message queue for user: {user.wa_id} \n {message_buffer}")

        # If lock is held, another process will handle this message
        if user_lock.locked():
            self.logger.info(f"Lock held for user {user.id}, message buffered")
            return None

        # Retrieve message history for the user
        message_history = await get_user_message_history(user.id)

        # Format conversation history for the model
        formatted_messages = self._format_conversation_history(message_history)

        async with user_lock:
            while True:  # We'll break out when no new messages arrive during processing
                try:
                    # Get current messages
                    messages_to_process = message_buffer.copy()

                    if not messages_to_process:  # Shouldn't happen, but just in case
                        self.logger.warning(
                            "No messages to process for user: {user.wa_id}"
                        )
                        message_buffer.clear()
                        self._cleanup_user(user.id)
                        return None

                    # Create messages list for API call with history and current messages
                    combined = "\n".join(messages_to_process)
                    api_messages = [
                        *formatted_messages,
                        {"role": "user", "content": combined},
                    ]

                    # Generate response using Together API
                    response = await self.client.chat.completions.create(
                        model=llm_settings.llm_model_name,
                        messages=api_messages,
                    )

                    # Check if new messages arrived during processing
                    if len(self._get_message_buffer(user.id)) > len(
                        messages_to_process
                    ):
                        self.logger.info(
                            "New messages arrived during processing, restarting"
                        )
                        continue  # Restart processing with all messages

                    # No new messages, we can return the response
                    message_buffer.clear()  # Only clear if we're actually returning a response
                    self._cleanup_user(user.id)  # Clean up empty structures
                    return response.choices[0].message.content if response else None

                except Exception as e:
                    self.logger.error(f"Error processing messages: {e}")
                    # On error, preserve messages and clean up
                    self._cleanup_user(user.id)
                    return None

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

    # async def _handle_tool_call(
    #     self,
    #     tool: Any,
    #     func: Callable[..., Any],
    #     verbose: bool = False,
    # ) -> Tuple[str, str]:
    #     """
    #     Handle tool calls by parsing arguments and executing the provided function.
    #     """
    #     try:
    #         # Parse and validate arguments
    #         arguments = json.loads(tool.function.arguments)
    #         if not isinstance(arguments, dict):
    #             raise ValueError("Parsed arguments are not in dictionary format.")

    #         # Call the function with unpacked arguments
    #         response_message = await func(**arguments)
    #         response_message = str(response_message)

    #     except json.JSONDecodeError as e:
    #         response_message = f"JSONDecodeError: {str(e)}"
    #         self.logger.error(response_message)
    #     except KeyError as e:
    #         response_message = f"Missing required argument: {str(e)}"
    #         self.logger.error(response_message)
    #     except Exception as e:
    #         response_message = f"An unexpected error occurred: {str(e)}"
    #         self.logger.error(response_message)
    #     else:
    #         self.logger.debug("Function executed successfully.")
    #     finally:
    #         if verbose:
    #             self.logger.debug(
    #                 f"🛠 Tool call: {tool.function.name}({str(tool.function.arguments)})"
    #             )
    #             self.logger.debug(f"Returned: {response_message}")

    #         return {
    #             "tool_call_id": tool.id,
    #             "output": response_message,
    #         }

    # async def _wait_for_run_completion(
    #     self,
    #     run: Any,
    #     thread: Thread,
    #     wa_id: str,
    #     verbose: bool = False,
    # ) -> str:
    #     """
    #     Wait for the completion of an OpenAI run and handle required actions.

    #     Args:
    #         run: The current OpenAI run object.
    #         thread_id: The thread ID of the current session.
    #         wa_id: The WhatsApp ID of the user.
    #         verbose: Whether to log detailed information.

    #     Returns:
    #         The most recent message generated by the assistant, if successful.
    #     """
    #     # TODO: add a timeout to avoid infinite loops
    #     while run.status != "completed":
    #         await asyncio.sleep(0.5)  # Is this necessary?
    #         self.logger.info(f"🏃‍♂️ Run status: {run.status}")

    #         # Retrieve the latest run status
    #         run = await self.client.beta.threads.runs.retrieve(
    #             thread_id=thread.id, run_id=run.id
    #         )

    #         if run.status == "requires_action":
    #             self.logger.info("🔧 Action required")

    #             tool_outputs = []
    #             # TODO: all tool calls can be handled concurrently
    #             for tool in run.required_action.submit_tool_outputs.tool_calls:
    #                 if tool.function.name == "generate_exercise":
    #                     # TODO: these can happen concurrently to be more efficient (use asyncio.gather())
    #                     await self._send_tool_execution_message(
    #                         wa_id, "🔄 Generating exercise..."
    #                     )
    #                     tool_output = await self._handle_tool_call(
    #                         tool, generate_exercise, verbose=verbose
    #                     )

    #                     tool_outputs.append(tool_output)

    #             try:
    #                 # Submit the tool outputs
    #                 await self.client.beta.threads.runs.submit_tool_outputs(
    #                     thread_id=thread.id,
    #                     run_id=run.id,
    #                     tool_outputs=tool_outputs,
    #                 )
    #             except openai.OpenAIError as e:
    #                 self.logger.error(f"Error submitting tool outputs: {e}")
    #                 return json.dumps({"error": str(e)})

    #         # Handle terminal run statuses
    #         if run.status in ["expired", "failed", "cancelled", "incomplete"]:
    #             error_message = f"OpenAI assistant ended the run {run.id} with the status {run.status}"
    #             self.logger.error(error_message)
    #             return json.dumps({"error": error_message})

    #     self.logger.info("🏁 Run completed")
    #     return await self._get_latest_assistant_message(thread.id)

    # async def _send_tool_execution_message(self, wa_id: str, msg: str) -> None:
    #     # Send a message indicating tool execution to the user.
    #     data = get_text_payload(wa_id, msg)
    #     self.db.store_message(wa_id, msg, role="twiga")
    #     await whatsapp_client.send_message(data)

    # async def _get_latest_assistant_message(self, thread_id: str) -> str:
    #     # Retrieve the most recent message generated by the assistant.
    #     messages = await self.client.beta.threads.messages.list(thread_id=thread_id)
    #     if messages.data:
    #         return messages.data[0].content[0].text.value  # TODO: Error handling
    #     return ""

    # async def _run_assistant(
    #     self, wa_id: str, thread: Thread, verbose: bool = False
    # ) -> str:
    #     try:
    #         # Check if self.assistant has been initialized
    #         if self.assistant is None:
    #             self.assistant = await self.client.beta.assistants.retrieve(
    #                 llm_settings.twiga_openai_assistant_id
    #             )

    #         # Create a new run
    #         run = await self.client.beta.threads.runs.create(
    #             thread_id=thread.id,
    #             assistant_id=self.assistant.id,
    #         )

    #         # Wait for the run to complete and handle actions
    #         return await self._wait_for_run_completion(run, thread, wa_id, verbose)

    #     except openai.OpenAIError as e:
    #         self.logger.error(f"Error during assistant run: {e}")
    #         return json.dumps({"error": str(e)})


llm_client = LLMClient()
