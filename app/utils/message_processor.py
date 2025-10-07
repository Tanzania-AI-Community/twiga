import asyncio
from typing import List
from app.database.models import Message


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
