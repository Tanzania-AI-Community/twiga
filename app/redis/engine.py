import redis.asyncio as redis
import logging
from app.config import settings

logger = logging.getLogger(__name__)

redis_pool = None
redis_client = None
redis_available = False


async def init_redis():
    """Initialize Redis connection. If Redis is not available, log warning and continue."""
    global redis_pool, redis_client, redis_available
    try:
        if not settings.redis_url:
            logger.warning("Redis URL not configured - Redis features disabled")
            redis_available = False
            return

        redis_pool = redis.ConnectionPool.from_url(
            settings.redis_url.get_secret_value()
        )
        redis_client = redis.Redis(connection_pool=redis_pool)
        await verify_redis_connection()
        redis_available = True
        logger.info("Redis connection established ✅")
    except Exception as e:
        logger.warning(f"Redis initialization failed: {e} - Redis features disabled")
        redis_available = False
        redis_client = None
        redis_pool = None


async def verify_redis_connection():
    global redis_client
    if redis_client is None:
        raise redis.ConnectionError("Redis client is not initialized")
    await redis_client.ping()
    logger.debug("Redis connection verified")


def get_redis_client():
    """Get Redis client. Returns None if Redis is not available."""
    global redis_client, redis_available
    if not redis_available or redis_client is None:
        return None
    return redis_client


def is_redis_available() -> bool:
    """Check if Redis is available for use."""
    global redis_available
    return redis_available


async def disconnect_redis():
    global redis_client, redis_available
    if redis_client:
        try:
            await redis_client.aclose()
            logger.info("Redis connection closed 🔒")
        except Exception as e:
            logger.warning(f"Error closing Redis connection: {e}")
    redis_available = False
