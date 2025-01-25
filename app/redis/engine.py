import redis.asyncio as redis
import logging
from app.config import settings

logger = logging.getLogger(__name__)

redis_pool = None
redis_client = None


async def init_redis():
    global redis_pool, redis_client
    try:
        redis_pool = redis.ConnectionPool.from_url(settings.redis_url)
        redis_client = redis.Redis(connection_pool=redis_pool)
        await verify_redis_connection()
        logger.debug("Redis connection established")
    except Exception as e:
        logger.error(f"Redis initialization failed: {e}")
        raise


async def verify_redis_connection():
    global redis_client
    if redis_client is None:
        logger.error("Redis client is not initialized")
        raise redis.ConnectionError("Redis client is not initialized")
    try:
        await redis_client.ping()
        logger.debug("Redis connection verified")
    except redis.ConnectionError as e:
        logger.error(f"Redis connection verification failed: {e}")
        raise


def get_redis_client():
    global redis_client
    if redis_client is None:
        raise redis.ConnectionError("Redis client is not initialized")
    return redis_client


async def disconnect_redis():
    global redis_client
    if redis_client:
        await redis_client.aclose()
        logger.info("Redis connection closed 🔒")
