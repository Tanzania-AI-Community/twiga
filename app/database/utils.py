from time import time
import logging
from urllib.parse import urlparse

from app.config import settings


logger = logging.getLogger(__name__)


# TODO: Currently not using this but might want to do something like this in the future
async def log_slow_query(query_name: str, start_time: float):
    duration = time() - start_time
    if duration > 1.0:  # Log queries taking more than 1 second
        logger.warning(f"Slow query detected: {query_name} took {duration:.2f} seconds")


def get_database_url() -> str:
    """Get formatted database URL from settings"""
    database_uri = urlparse(settings.database_url.get_secret_value())

    if "neon.tech" in database_uri.hostname:
        return f"postgresql+asyncpg://{database_uri.username}:{database_uri.password}@{database_uri.hostname}{database_uri.path}?ssl=require"

    return f"postgresql+asyncpg://{database_uri.username}:{database_uri.password}@{database_uri.hostname}:{database_uri.port}{database_uri.path}"
