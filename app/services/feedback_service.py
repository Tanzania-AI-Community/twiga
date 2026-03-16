import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi.responses import JSONResponse

import app.database.db as db
import app.database.enums as enums
import app.database.models as models
from app.monitoring.metrics import record_messages_generated
from app.services.whatsapp_service import whatsapp_client
from app.utils.string_manager import StringCategory, strings


class FeedbackService:
    _OPTION_MAP: dict[str, tuple[enums.FeedbackResponseType, bool]] = {
        "feedback:positive": (enums.FeedbackResponseType.positive, False),
        "feedback:neutral": (enums.FeedbackResponseType.neutral, False),
        "feedback:negative": (enums.FeedbackResponseType.negative, False),
        "feedback:opt_out": (enums.FeedbackResponseType.opt_out, True),
    }

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    @property
    def feedback_options(self) -> list[dict[str, str]]:
        return [
            {
                "id": "feedback:positive",
                "title": strings.get_string(StringCategory.FEEDBACK, "option_positive"),
            },
            {
                "id": "feedback:neutral",
                "title": strings.get_string(StringCategory.FEEDBACK, "option_neutral"),
            },
            {
                "id": "feedback:negative",
                "title": strings.get_string(StringCategory.FEEDBACK, "option_negative"),
            },
            {
                "id": "feedback:opt_out",
                "title": strings.get_string(StringCategory.FEEDBACK, "option_opt_out"),
            },
        ]

    @staticmethod
    def _extract_interactive_reply(
        message_info: dict[str, Any]
    ) -> Optional[dict[str, str]]:
        message = message_info.get("message") or {}
        if message.get("type") != "interactive":
            return None

        interactive = message.get("interactive") or {}
        interactive_type = interactive.get("type")
        if interactive_type == "button_reply":
            data = interactive.get("button_reply") or {}
            reply_id = data.get("id")
            title = data.get("title")
            if isinstance(reply_id, str) and isinstance(title, str):
                return {"id": reply_id, "title": title}
        elif interactive_type == "list_reply":
            data = interactive.get("list_reply") or {}
            reply_id = data.get("id")
            title = data.get("title")
            if isinstance(reply_id, str) and isinstance(title, str):
                return {"id": reply_id, "title": title}

        return None

    async def send_feedback_invite(
        self, invite: models.FeedbackInvite, user: models.User
    ) -> None:
        assert user.id is not None
        prompt = strings.get_string(StringCategory.FEEDBACK, "prompt")

        await whatsapp_client.send_message(
            user.wa_id,
            prompt,
            options=self.feedback_options,
        )
        record_messages_generated("feedback_invite")

        await db.create_new_message(
            models.Message(
                user_id=user.id,
                role=enums.MessageRole.assistant,
                content=prompt,
            )
        )

    async def try_handle_feedback_reply(
        self, user: models.User, message_info: dict[str, Any]
    ) -> Optional[JSONResponse]:
        """
        Handle feedback option replies if a user has an open feedback invite.
        Returns a response if handled, otherwise None.
        """
        assert user.id is not None

        reply = self._extract_interactive_reply(message_info)
        if reply is None:
            return None

        option_id = reply["id"]
        option_title = reply["title"]

        if option_id not in self._OPTION_MAP:
            return None

        invite = await db.get_latest_open_feedback_invite(user.id)
        if invite is None:
            return None

        user_message_text = message_info.get("extracted_content") or option_title
        await db.create_new_message(
            models.Message(
                user_id=user.id,
                role=enums.MessageRole.user,
                content=user_message_text,
            )
        )

        response_type, should_opt_out = self._OPTION_MAP[option_id]
        await db.record_feedback_response(
            invite_id=invite.id,
            user_id=user.id,
            response_type=response_type,
            selected_option_id=option_id,
            selected_option_title=option_title,
        )

        if should_opt_out:
            user.feedback_opted_out = True
            user.feedback_opted_out_at = datetime.now(timezone.utc)
            await db.update_user(user)
            ack = strings.get_string(StringCategory.FEEDBACK, "opt_out_ack")
        else:
            ack = strings.get_string(StringCategory.FEEDBACK, "thanks")

        await whatsapp_client.send_message(user.wa_id, ack)
        record_messages_generated("feedback_ack")
        await db.create_new_message(
            models.Message(
                user_id=user.id,
                role=enums.MessageRole.assistant,
                content=ack,
            )
        )

        return JSONResponse(content={"status": "ok"}, status_code=200)


feedback_client = FeedbackService()
