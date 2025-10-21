#!/usr/bin/env python3
"""
Cron job script to mark users as inactive if they haven't exchanged messages in the configured time period.

This script should be run by an external cron job to:
1. Find active users who haven't exchanged messages in the configured hours
2. Mark them as inactive
3. Log the activity for monitoring

Usage:
    uv run python scripts/crons/mark_inactive_users_cron.py

Cron job example (run every hour):
    0 * * * * cd /path/to/twiga && uv run python scripts/crons/mark_inactive_users_cron.py

Required Environment Variables:
    - DATABASE_URL: PostgreSQL connection string
    - USER_INACTIVITY_THRESHOLD_HOURS: Hours after which user becomes inactive (default: 24)
"""

import asyncio
import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.database.enums import UserState

# Import cron helpers
from helpers import (
    initialize_db,
    get_users_to_mark_inactive,
    update_user,
    setup_logging,
)
from helpers.logging import (
    log_job_start,
    log_job_completion,
    log_processing_item,
    log_item_success,
    log_item_error,
)

# Configuration from environment
USER_INACTIVITY_THRESHOLD_HOURS = int(
    os.getenv("USER_INACTIVITY_THRESHOLD_HOURS", "24")
)

# Set up logging
logger = setup_logging(
    name="mark_inactive_users_cron",
    log_file="/tmp/twiga_mark_inactive_users.log",
)


async def mark_inactive_users():
    """
    Find active users who haven't exchanged messages in the configured hours and mark them as inactive.
    """
    log_job_start(
        logger,
        "mark inactive users job",
        inactivity_threshold_hours=USER_INACTIVITY_THRESHOLD_HOURS,
    )

    try:
        # Initialize database
        initialize_db()

        # Get all users who should be marked as inactive
        users_to_mark_inactive = await get_users_to_mark_inactive(
            USER_INACTIVITY_THRESHOLD_HOURS
        )

        if not users_to_mark_inactive:
            logger.info("No users found to mark as inactive")
            return

        logger.info(f"Found {len(users_to_mark_inactive)} users to mark as inactive")

        success_count = 0
        error_count = 0

        for user in users_to_mark_inactive:
            try:
                log_processing_item(logger, "user", user.wa_id)

                # Update user state to inactive
                user.state = UserState.inactive
                await update_user(user)

                log_item_success(logger, "user", user.wa_id, "marked as inactive")
                success_count += 1

            except Exception as e:
                log_item_error(logger, "user", user.wa_id, "mark as inactive", e)
                error_count += 1
                # Continue with next user even if one fails
                continue

        log_job_completion(
            logger, "Mark inactive users job", success_count, error_count
        )

        # Exit with error code if any failures occurred
        if error_count > 0:
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
