#!/usr/bin/env python3
"""
Cron job script to send reminder template messages to inactive users.

This script should be run by an external cron job to:
1. Find users inactive for the configured number of days
2. Send a WhatsApp template reminder message
3. Persist the sent reminder in the messages table

Usage:
    uv run python scripts/crons/send_reminder_messages_cron.py

Cron job example (run daily at 9:00 UTC):
    0 9 * * * cd /path/to/twiga && uv run python scripts/crons/send_reminder_messages_cron.py

Required Environment Variables:
    - DATABASE_URL: PostgreSQL connection string
    - WHATSAPP_API_TOKEN: WhatsApp Cloud API access token
    - WHATSAPP_CLOUD_NUMBER_ID: WhatsApp Business phone number ID
    - META_API_VERSION: Meta API version (e.g., v22.0)
    - REMINDER_TEMPLATE_ID: WhatsApp template name for reminder sends
    - MOCK_WHATSAPP: Set to true to skip sending actual WhatsApp messages (default: false)

Optional Environment Variables:
    - REMINDER_INACTIVITY_DAYS: Days of inactivity before reminder (default: 7)
    - REMINDER_COOLDOWN_DAYS: Minimum days between reminders per user (default: 7)
    - REMINDER_TEMPLATE_LANGUAGE: WhatsApp template language code (default: en_US)
"""

import asyncio
import os
import random
import sys
from typing import Iterable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Import cron helpers
from app.database.enums import MessageRole
from app.database.models import Message, User
from app.utils.string_manager import StringCategory, strings
from scripts.crons.helpers import (
    REMINDER_MESSAGE_TOOL_NAME,
    WhatsAppClient,
    create_message,
    get_users_for_reminder,
    initialize_db,
    setup_logging,
)
from scripts.crons.helpers.logging import (
    log_item_error,
    log_item_success,
    log_job_completion,
    log_job_start,
    log_processing_item,
)

REMINDER_TEMPLATE_ID = os.getenv("REMINDER_TEMPLATE_ID", "twiga_inactive_reminder")
REMINDER_INACTIVITY_DAYS = int(os.getenv("REMINDER_INACTIVITY_DAYS", "7"))
REMINDER_COOLDOWN_DAYS = int(os.getenv("REMINDER_COOLDOWN_DAYS", "7"))
REMINDER_TEMPLATE_LANGUAGE = os.getenv("REMINDER_TEMPLATE_LANGUAGE", "en_US")

logger = setup_logging(
    name="send_reminder_messages_cron",
    log_file="/tmp/twiga_send_reminder_messages.log",
)


def _get_reminder_strings() -> list[str]:
    reminder_strings = strings.get_category(StringCategory.REMINDER)

    if (
        not isinstance(reminder_strings, list)
        or len(reminder_strings) == 0
        or not all(isinstance(item, str) and item.strip() for item in reminder_strings)
    ):
        raise ValueError(
            "String category 'reminder' must be a non-empty list of strings."
        )

    return [reminder_string.strip() for reminder_string in reminder_strings]


def _build_reminder_db_message(*, user_id: int, reminder_text: str) -> Message:
    return Message(
        user_id=user_id,
        role=MessageRole.assistant,
        content=reminder_text,
        tool_name=REMINDER_MESSAGE_TOOL_NAME,
        is_present_in_conversation=True,
    )


async def _send_reminder_to_user(
    *,
    user: User,
    reminder_templates: list[str],
    whatsapp_client: WhatsAppClient,
) -> None:
    log_processing_item(logger, "user", user.wa_id)

    reminder_message = random.choice(reminder_templates)

    await whatsapp_client.send_template_message(
        user.wa_id,
        REMINDER_TEMPLATE_ID,
        language_code=REMINDER_TEMPLATE_LANGUAGE,
        body_text_params=[reminder_message],
        include_image_header=False,
    )

    if user.id is None:
        raise ValueError(f"User ID is missing for user with wa_id={user.wa_id}")

    await create_message(
        _build_reminder_db_message(user_id=user.id, reminder_text=reminder_message)
    )

    log_item_success(logger, "user", user.wa_id, "sent reminder to")


async def _process_users(
    *,
    users_for_reminder: Iterable[User],
    reminder_templates: list[str],
    whatsapp_client: WhatsAppClient,
) -> tuple[int, int]:
    success_count = 0
    error_count = 0

    for user in users_for_reminder:
        try:
            await _send_reminder_to_user(
                user=user,
                reminder_templates=reminder_templates,
                whatsapp_client=whatsapp_client,
            )
            success_count += 1
        except Exception as exc:
            log_item_error(logger, "user", user.wa_id, "send reminder to", exc)
            error_count += 1

    return success_count, error_count


async def send_reminder_messages() -> None:
    """Send reminder template messages to users inactive beyond the threshold."""
    log_job_start(
        logger,
        "send reminder messages job",
        reminder_template_id=REMINDER_TEMPLATE_ID,
        inactivity_days=REMINDER_INACTIVITY_DAYS,
        reminder_cooldown_days=REMINDER_COOLDOWN_DAYS,
        language=REMINDER_TEMPLATE_LANGUAGE,
    )

    try:
        initialize_db()
        reminder_strings = _get_reminder_strings()
        users_for_reminder = await get_users_for_reminder(
            inactivity_days=REMINDER_INACTIVITY_DAYS,
            reminder_cooldown_days=REMINDER_COOLDOWN_DAYS,
        )

        if not users_for_reminder:
            logger.info("No users found eligible for reminder messages")
            return

        logger.info(f"Found {len(users_for_reminder)} users eligible for reminders")

        async with WhatsAppClient() as whatsapp_client:
            success_count, error_count = await _process_users(
                users_for_reminder=users_for_reminder,
                reminder_templates=reminder_strings,
                whatsapp_client=whatsapp_client,
            )

        log_job_completion(
            logger, "Send reminder messages job", success_count, error_count
        )

        if error_count > 0:
            sys.exit(1)

    except Exception as e:
        logger.error(f"Reminder job failed: {str(e)}")
        sys.exit(1)


async def main():
    """Main entry point."""
    try:
        await send_reminder_messages()
        logger.info("Reminder cron job completed successfully")
    except Exception as e:
        logger.error(f"Critical error in reminder cron job: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
