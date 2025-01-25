from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import logging
from app.redis.engine import get_redis_client
from app.config import settings

logger = logging.getLogger(__name__)

EAT = pytz.timezone(settings.timezone)


async def reset_daily_limits():
    redis_client = get_redis_client()
    # Note: Maybe before deleting the keys, we can send a report of the daily usage to the admin
    # Log all the keys and their values before deleting them
    keys = await redis_client.keys("rate_limit:*")
    for key in keys:
        value = await redis_client.get(key)
        logger.info(f"Key: {key}, Value: {value}")
    keys = await redis_client.keys("rate_limit:*")
    for key in keys:
        await redis_client.delete(key)
    logger.info("Daily limits reset successfully")


def start_scheduler():
    scheduler = AsyncIOScheduler(timezone=EAT)
    scheduler.add_job(reset_daily_limits, CronTrigger(hour=0, minute=0))
    scheduler.start()
    logger.debug("Scheduler started successfully")
