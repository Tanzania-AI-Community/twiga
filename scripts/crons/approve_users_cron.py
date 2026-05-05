#!/usr/bin/env python3
"""
Cron job script to approve users and send welcome messages.

This script should be run by an external cron job to:
1. Find users with UserState.new (approved by dashboard)
2. Send welcome messages to those users
3. Update their state to active

Usage:
    uv run python scripts/crons/approve_users_cron.py

Cron job example (run every 5 minutes):
    */5 * * * * cd /path/to/twiga && uv run python scripts/crons/approve_users_cron.py

Required Environment Variables:
    - DATABASE_URL: PostgreSQL connection string
    - WHATSAPP_API_TOKEN: WhatsApp Cloud API access token
    - WHATSAPP_CLOUD_NUMBER_ID: WhatsApp Business phone number ID
    - META_API_VERSION: Meta API version (e.g., v22.0)
    - WELCOME_TEMPLATE_ID: WhatsApp template message ID (default: twiga_registration_approved)
    - MOCK_WHATSAPP: Set to true to skip sending actual WhatsApp messages (default: false)
"""

import asyncio
import os
import sys

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Import cron helpers
from helpers import (
    WhatsAppClient,
    create_message,
    get_users_by_state,
    initialize_db,
    setup_logging,
    update_user,
)
from helpers.logging import (
    log_item_error,
    log_item_success,
    log_job_completion,
    log_job_start,
    log_processing_item,
)

from app.database.enums import MessageRole, UserState
from app.database.models import Message

# Configuration from environment
WELCOME_TEMPLATE_ID = os.getenv("WELCOME_TEMPLATE_ID", "twiga_registration_approved")

# Set up logging
logger = setup_logging(
    name="approve_users_cron",
    log_file="/tmp/twiga_approve_users.log",
)


async def approve_and_welcome_users():
    """
    Find users with UserState.new (approved by dashboard) and:
    1. Send welcome messages
    2. Update their state to active
    3. Log the message to database
    """
    log_job_start(
        logger,
        "user approval and welcome message job",
        template_id=WELCOME_TEMPLATE_ID,
    )

    try:
        # Initialize database
        initialize_db()

        # Get all users with state 'new' (approved by dashboard but not yet welcomed)
        new_users = await get_users_by_state(UserState.approved)

        if not new_users:
            logger.info("No new users found to approve and welcome")
            return

        logger.info(f"Found {len(new_users)} users to approve and welcome")

        success_count = 0
        error_count = 0

        # Create WhatsApp client
        async with WhatsAppClient() as whatsapp_client:
            for user in new_users:
                try:
                    log_processing_item(logger, "user", user.wa_id)

                    # Send welcome template message via WhatsApp
                    await whatsapp_client.send_template_message(
                        user.wa_id, WELCOME_TEMPLATE_ID
                    )
                    logger.info(f"Sent welcome template message to user: {user.wa_id}")

                    # Update user state to onboarding
                    user.state = UserState.onboarding
                    await update_user(user)

                    # Create a message record in the database
                    assert user.id is not None
                    welcome_db_message = Message(
                        user_id=user.id,
                        role=MessageRole.assistant,
                        content=f"Welcome template sent: {WELCOME_TEMPLATE_ID}",
                    )
                    await create_message(welcome_db_message)

                    log_item_success(
                        logger, "user", user.wa_id, "approved and activated"
                    )
                    success_count += 1

                except Exception as e:
                    log_item_error(logger, "user", user.wa_id, "process", e)
                    error_count += 1
                    # Continue with next user even if one fails
                    continue

        log_job_completion(logger, "User approval job", success_count, error_count)

        # Exit with error code if any failures occurred
        if error_count > 0:
            sys.exit(1)

    except Exception as e:
        logger.error(f"User approval job failed: {str(e)}")
        sys.exit(1)


async def main():
    """Main entry point"""
    try:
        await approve_and_welcome_users()
        logger.info("User approval cron job completed successfully")
    except Exception as e:
        logger.error(f"Critical error in user approval cron job: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
