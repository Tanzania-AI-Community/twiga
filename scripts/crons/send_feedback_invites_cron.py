#!/usr/bin/env python3
"""
Cron job to enqueue and send feedback prompts for idle chats.

Usage:
    uv run python scripts/crons/send_feedback_invites_cron.py
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

# Add app root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.config import settings
from app.database import db
from app.services.feedback_service import feedback_client

logger = logging.getLogger("send_feedback_invites_cron")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


async def enqueue_feedback_invites() -> int:
    eligible_users = await db.get_users_eligible_for_feedback_invite(
        idle_minutes=settings.feedback_idle_minutes,
        limit=settings.feedback_scan_limit,
    )

    enqueued = 0
    now = datetime.now(timezone.utc)

    for user in eligible_users:
        if user.id is None or user.last_message_at is None:
            continue

        try:
            await db.create_feedback_invite(
                user_id=user.id,
                last_message_at_snapshot=user.last_message_at,
                scheduled_at=now,
            )
            enqueued += 1
        except Exception as e:
            # Unique constraint races are acceptable in distributed runs.
            logger.warning("Skipping invite creation for user %s: %s", user.wa_id, e)

    return enqueued


async def send_pending_feedback_invites() -> tuple[int, int]:
    pending_invites = await db.get_pending_feedback_invites(
        limit=settings.feedback_scan_limit
    )

    sent = 0
    failed = 0

    for invite in pending_invites:
        user = await db.get_user_by_id(invite.user_id)
        if user is None or user.id is None:
            await db.mark_feedback_invite_failed(invite.id, "user_not_found")
            failed += 1
            continue

        if user.feedback_opted_out:
            await db.mark_feedback_invite_failed(invite.id, "user_opted_out")
            failed += 1
            continue

        try:
            await feedback_client.send_feedback_invite(invite=invite, user=user)
            await db.mark_feedback_invite_sent(invite.id)
            sent += 1
        except Exception as e:
            await db.mark_feedback_invite_failed(invite.id, str(e))
            failed += 1

    return sent, failed


async def main() -> None:
    logger.info(
        "Starting feedback invite cron with idle_minutes=%s, scan_limit=%s, expiry_hours=%s",
        settings.feedback_idle_minutes,
        settings.feedback_scan_limit,
        settings.feedback_invite_expiry_hours,
    )

    expired = await db.expire_stale_feedback_invites(
        expiry_hours=settings.feedback_invite_expiry_hours,
        limit=settings.feedback_scan_limit,
    )
    enqueued = await enqueue_feedback_invites()
    sent, failed = await send_pending_feedback_invites()

    logger.info(
        "Feedback cron completed. Expired=%s Enqueued=%s Sent=%s Failed=%s",
        expired,
        enqueued,
        sent,
        failed,
    )


if __name__ == "__main__":
    asyncio.run(main())
