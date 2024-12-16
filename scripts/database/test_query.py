import asyncio
from urllib.parse import urlparse
from sqlmodel import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
import logging
import time
from contextlib import contextmanager

# Import all your models
from app.database.models import User
from app.config import settings


def get_database_url() -> str:
    """Get formatted database URL from settings"""
    if settings.env_file == ".env.local":
        return settings.database_url.get_secret_value()
    database_uri = urlparse(settings.database_url.get_secret_value())
    return f"postgresql+asyncpg://{database_uri.username}:{database_uri.password}@{database_uri.hostname}{database_uri.path}"


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Create async engine
engine = create_async_engine(get_database_url(), echo=False)


@contextmanager
def timer(description: str):
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    logger.info(f"{description}: {elapsed:.3f} seconds")


async def test_query():
    """Run a test query to ensure database is set up correctly"""
    try:
        async with AsyncSession(engine) as session:
            # Example query to fetch all classes
            with timer("Database query execution time"):
                stmt = select(User)
                result = await session.execute(stmt)

            users = result.scalars().all()

        for user in users:
            logger.info(f"User: {user.name} - {user.wa_id}")
    except Exception as e:
        logger.error(f"Error running test query: {str(e)}")
        raise


# Run the test query
asyncio.run(test_query())
