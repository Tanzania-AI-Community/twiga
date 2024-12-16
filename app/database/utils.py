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
    # database_url = "postgresql+asyncpg://{db_user}:{db_password}@{db_server_name}:{db_port}/{db_name}".format(
    #     db_user=settings.database_user.get_secret_value(),
    #     db_password=settings.database_password.get_secret_value(),
    #     db_server_name=settings.database_server_name.get_secret_value(),
    #     db_port=settings.database_port.get_secret_value(),
    #     db_name=settings.database_name.get_secret_value(),
    # )
    # return database_url
    if settings.env_file == ".env.local":
        return settings.database_url.get_secret_value()
    database_uri = urlparse(settings.database_url.get_secret_value())
    return f"postgresql+asyncpg://{database_uri.username}:{database_uri.password}@{database_uri.hostname}{database_uri.path}"

