"""Conversational onboarding: the intro, message routing and the completion gate.

The agent (in onboarding mode) collects the name, subjects and forms through
the profile tools. This service only decides which messages reach the agent
and moves the teacher to `active` once the saved profile is complete. The
model never decides that onboarding is finished.
"""

import logging

from fastapi.responses import JSONResponse

from app.clients.agent_modes import AgentMode
from app.clients.whatsapp_client import whatsapp_client
from app.database import db
from app.database.enums import MessageRole, OnboardingState, UserState
from app.database.models import Message, User
from app.services.messaging_service import messaging_client
from app.services.profile import ProfileSnapshot
from app.utils.string_manager import StringCategory, strings
from app.utils.whatsapp_utils import ValidMessageType, get_valid_message_type

# Text (including transcribed voice notes and "help"/"settings") goes to the agent
_AGENT_MESSAGE_TYPES = frozenset({ValidMessageType.CHAT, ValidMessageType.COMMAND})


def _onboarding_state_for(snapshot: ProfileSnapshot) -> OnboardingState:
    if snapshot.complete:
        return OnboardingState.completed
    if snapshot.name:
        return OnboardingState.personal_info_submitted
    return OnboardingState.new


class OnboardingService:
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    async def send_intro(self, user: User) -> bool:
        """Send the fixed first message: what Twiga is, the privacy note, and the ask."""
        intro = strings.get_string(StringCategory.ONBOARDING, "intro")
        return await self.send_recorded_message(user, intro)

    async def handle_message(
        self, user: User, message_info: dict, user_message: Message
    ) -> JSONResponse:
        message_type = get_valid_message_type(message_info)
        if message_type in _AGENT_MESSAGE_TYPES:
            await messaging_client.generate_and_deliver(
                user, user_message, mode=AgentMode.onboarding
            )
            await self.update_progress(user)
        else:
            text_only = strings.get_string(StringCategory.ONBOARDING, "text_only")
            await self.send_recorded_message(user, text_only)
        return JSONResponse(content={"status": "ok"}, status_code=200)

    async def update_progress(self, user: User) -> bool:
        """Sync `onboarding_state` with the saved profile; True when just completed.

        Idempotent: once the teacher is active it does nothing, so a buffered
        message or a repeated call can never complete onboarding twice.
        """
        fresh_user = await db.get_user_by_waid(user.wa_id)
        if fresh_user is None or fresh_user.state != UserState.onboarding:
            return False

        target_state = _onboarding_state_for(ProfileSnapshot.from_user(fresh_user))
        if target_state == fresh_user.onboarding_state:
            return False

        fresh_user.onboarding_state = target_state
        completed = target_state == OnboardingState.completed
        if completed:
            fresh_user.state = UserState.active
        await db.update_user(fresh_user)

        self.logger.info(
            "onboarding.progress user_id=%s onboarding_state=%s",
            fresh_user.id,
            target_state.value,
        )
        return completed

    async def send_recorded_message(self, user: User, content: str) -> bool:
        """Send a message and record it only when WhatsApp accepts the send."""
        if user.id is None:
            raise ValueError("User ID is unexpectedly None during onboarding.")

        sent = await whatsapp_client.send_message(user.wa_id, content)
        if not sent:
            return False

        await db.create_new_message_by_fields(
            user_id=user.id,
            role=MessageRole.assistant,
            content=content,
            is_present_in_conversation=True,
        )
        return True


onboarding_client = OnboardingService()
