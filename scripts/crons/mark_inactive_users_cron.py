#!/usr/bin/env python3
"""
Cron job script to mark users as inactive if they haven't exchanged messages in the configured time period.

This script should be run by an external cron job to:
1. Find active users who haven't exchanged messages in the configured hours
2. Mark them as inactive
3. Log the activity for monitoring

Usage:
    python scripts/crons/mark_inactive_users_cron.py

Cron job example (run every hour):
    0 * * * * cd /path/to/twiga && uv run python scripts/crons/mark_inactive_users_cron.py
"""

import asyncio
import logging
import sys
import os
from typing import List

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import db
from app.database.models import User
from app.database.enums import UserState
from app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/tmp/twiga_mark_inactive_users.log", mode="a"),
    ],
)

logger = logging.getLogger(__name__)


async def mark_inactive_users():
    """
    Find active users who haven't exchanged messages in the configured hours and mark them as inactive.
    """
    logger.info("Starting mark inactive users job")

    try:
        # Get the inactivity threshold from config
        hours_threshold = settings.user_inactivity_threshold_hours
        logger.info(f"Using inactivity threshold of {hours_threshold} hours")

        # Get all users who should be marked as inactive
        users_to_mark_inactive: List[User] = await db.get_users_to_mark_inactive(
            hours_threshold
        )

        if not users_to_mark_inactive:
            logger.info("No users found to mark as inactive")
            return

        logger.info(f"Found {len(users_to_mark_inactive)} users to mark as inactive")

        success_count = 0
        error_count = 0

        for user in users_to_mark_inactive:
            try:
                logger.info(f"Processing user: {user.wa_id}")

                # Update user state to inactive
                user.state = UserState.inactive
                await db.update_user(user)

                logger.info(f"Successfully marked user {user.wa_id} as inactive")
                success_count += 1

            except Exception as e:
                logger.error(f"Failed to mark user {user.wa_id} as inactive: {str(e)}")
                error_count += 1
                # Continue with next user even if one fails
                continue

        logger.info(
            f"Mark inactive users job completed. Success: {success_count}, Errors: {error_count}"
        )

        # Exit with error code if any failures occurred
        if error_count > 0:
            logger.warning(f"Job completed with {error_count} errors")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Mark inactive users job failed: {str(e)}")
        sys.exit(1)


async def main():
    """Main entry point"""
    try:
        await mark_inactive_users()
        logger.info("Mark inactive users cron job completed successfully")
    except Exception as e:
        logger.error(f"Critical error in mark inactive users cron job: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
