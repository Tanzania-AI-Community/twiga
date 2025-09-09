import logging
from typing import Optional
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import db
from app.database.models import Message
from app.database.enums import UserState, OnboardingState, MessageRole
from app.services.whatsapp_service import whatsapp_client
from app.utils.string_manager import strings, StringCategory
from app.config import settings

logger = logging.getLogger(__name__)

# East Africa Time timezone
EAT = pytz.timezone("Africa/Nairobi")

# Global scheduler instance
scheduler: Optional[AsyncIOScheduler] = None


async def send_welcome_message_to_new_users():
    """
    Daily cron job that sends welcome template messages to users with UserState.new
    and updates their state to onboarding.
    """
    logger.info("Starting daily welcome message job at noon EAT")

    try:
        # Get all users with state 'new'
        new_users = await db.get_users_by_state(UserState.new)

        if not new_users:
            logger.info("No new users found to send welcome messages")
            return

        # Get welcome message text for database record
        welcome_message = strings.get_string(StringCategory.ONBOARDING, "welcome")

        for user in new_users:
            try:
                # Send welcome template message
                await whatsapp_client.send_template_message(
                    user.wa_id, settings.welcome_template_id
                )
                logger.info(f"Sent welcome template message to user: {user.wa_id}")

                # Update user state to onboarding
                user.state = UserState.onboarding
                user.onboarding_state = OnboardingState.new
                await db.update_user(user)

                # Create a message record in the database
                assert user.id is not None
                welcome_db_message = Message(
                    user_id=user.id,
                    role=MessageRole.assistant,
                    content=welcome_message,
                )
                await db.create_new_message(welcome_db_message)

                logger.info(f"Updated user {user.wa_id} state to onboarding")

            except Exception as e:
                logger.error(f"Failed to process user {user.wa_id}: {str(e)}")
                # Continue with next user even if one fails
                continue

        logger.info(f"Completed welcome message job. Processed {len(new_users)} users")

    except Exception as e:
        logger.error(f"Welcome message job failed: {str(e)}")
        raise


def start_scheduler():
    """
    Initialize and start the scheduler with the daily welcome message job.
    """
    global scheduler

    if scheduler is not None:
        logger.warning("Scheduler is already running")
        return

    scheduler = AsyncIOScheduler(timezone=EAT)

    # Add job to run daily at noon EAT (12:00)
    scheduler.add_job(
        send_welcome_message_to_new_users,
        trigger=CronTrigger(hour=12, minute=0, timezone=EAT),
        id="daily_welcome_messages",
        name="Send welcome messages to new users",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started with daily welcome message job at noon EAT")


def stop_scheduler():
    """
    Stop the scheduler gracefully.
    """
    global scheduler

    if scheduler is not None:
        scheduler.shutdown(wait=True)
        scheduler = None
        logger.info("Scheduler stopped")
    else:
        logger.warning("Scheduler is not running")


def get_scheduler_status() -> dict:
    """
    Get the current status of the scheduler and its jobs.

    Returns:
        Dictionary containing scheduler status information
    """
    global scheduler

    if scheduler is None:
        return {"status": "stopped", "jobs": []}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run": (
                    job.next_run_time.isoformat() if job.next_run_time else None
                ),
                "trigger": str(job.trigger),
            }
        )

    return {
        "status": "running" if scheduler.running else "stopped",
        "timezone": str(scheduler.timezone),
        "jobs": jobs,
    }
