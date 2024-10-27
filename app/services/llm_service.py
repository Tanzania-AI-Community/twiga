import json
import logging
import asyncio
from typing import Any, Callable, List, Optional, Tuple
from together import AsyncTogether


from app.database.models import Message, MessageRole, User
from app.utils.whatsapp_utils import get_text_payload
from app.config import llm_settings
from app.database.db import get_user_message_history
from app.services.whatsapp_service import whatsapp_client
from assets.prompts import get_system_prompt
import app.database.db as db


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

                    for message in messages_to_process:
                        # Store messages in the database
                        await db.create_new_message(
                            user_id=user.id, content=message, role=MessageRole.user
                        )
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


llm_client = LLMClient()
