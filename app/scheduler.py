from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import logging
from app.redis.engine import get_redis_client

logger = logging.getLogger(__name__)

EAT = pytz.timezone("Africa/Nairobi")


async def reset_daily_limits():
    redis_client = get_redis_client()
    keys = await redis_client.keys("rate_limit:*")
    for key in keys:
        await redis_client.delete(key)
    logger.info("Daily limits reset successfully")


def start_scheduler():
    scheduler = AsyncIOScheduler(timezone=EAT)
    scheduler.add_job(reset_daily_limits, CronTrigger(hour=0, minute=0))
    scheduler.start()
    # logger.info("Scheduler started successfully")
