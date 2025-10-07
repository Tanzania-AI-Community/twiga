#!/usr/bin/env python3
"""
Cron job script to approve users and send welcome messages.

This script should be run by an external cron job to:
1. Find users with UserState.new (approved by dashboard)
2. Send welcome messages to those users
3. Update their state to active

Usage:
    python scripts/crons/approve_users_cron.py

Cron job example (run every 5 minutes):
    */5 * * * * cd /path/to/twiga && uv run python scripts/crons/approve_users_cron.py
"""

import asyncio
import logging
import sys
import os
from typing import List

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import db
from app.database.models import Message, User
from app.database.enums import UserState, MessageRole
from app.services.whatsapp_service import whatsapp_client
from app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/tmp/twiga_approve_users.log", mode="a"),
    ],
)

logger = logging.getLogger(__name__)


async def approve_and_welcome_users():
    """
    Find users with UserState.new (approved by dashboard) and:
    1. Send welcome messages
    2. Update their state to active
    3. Log the message to database
    """
    logger.info("Starting user approval and welcome message job")

    try:
        # Get all users with state 'new' (approved by dashboard but not yet welcomed)
        new_users: List[User] = await db.get_users_by_state(UserState.new)

        if not new_users:
            logger.info("No new users found to approve and welcome")
            return

        logger.info(f"Found {len(new_users)} users to approve and welcome")

        success_count = 0
        error_count = 0

        for user in new_users:
            try:
                logger.info(f"Processing user: {user.wa_id}")

                # Send welcome template message via WhatsApp
                await whatsapp_client.send_template_message(
                    user.wa_id, settings.welcome_template_id
                )
                logger.info(f"Sent welcome template message to user: {user.wa_id}")

                # Update user state to active
                user.state = UserState.active
                await db.update_user(user)

                # Create a message record in the database
                assert user.id is not None
                welcome_db_message = Message(
                    user_id=user.id,
                    role=MessageRole.assistant,
                    content=f"Welcome template sent: {settings.welcome_template_id}",
                )
                await db.create_new_message(welcome_db_message)

                logger.info(f"Successfully approved and activated user {user.wa_id}")
                success_count += 1

            except Exception as e:
                logger.error(f"Failed to process user {user.wa_id}: {str(e)}")
                error_count += 1
                # Continue with next user even if one fails
                continue

        logger.info(
            f"User approval job completed. Success: {success_count}, Errors: {error_count}"
        )

        # Exit with error code if any failures occurred
        if error_count > 0:
            logger.warning(f"Job completed with {error_count} errors")
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
