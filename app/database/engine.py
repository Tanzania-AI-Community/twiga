import asyncio
from urllib.parse import urlparse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, AsyncSession
from sqlmodel import text
from app.config import settings
from app.database.models import *
import logging


logger = logging.getLogger(__name__)


async def init_db(engine: AsyncEngine) -> None:
    """
    Initialize database connection and log basic PostgreSQL information.

    Args:
        engine: AsyncEngine instance for database connection
    """
    try:
        async with AsyncSession(engine) as session:
            # Check PostgreSQL version
            result = await session.execute(text("SELECT pg_catalog.version()"))
            version = result.scalar()
            logger.info(f"PostgreSQL version: {version}")

            # Check current schema
            result = await session.execute(text("SELECT current_schema()"))
            schema = result.scalar()
            logger.info(f"Current schema: {schema}")

            # Verify we can start a transaction
            logger.info("Successfully initiated database transaction")

            await session.commit()
            logger.info("Database initialization completed successfully")

    except Exception as e:
        logger.error(f"Database initialization failed: {str(e)}")
        raise


def get_database_url() -> str:
    """Get formatted database URL from settings"""
    database_uri = urlparse(settings.database_url.get_secret_value())
    return f"postgresql+asyncpg://{database_uri.username}:{database_uri.password}@{database_uri.hostname}{database_uri.path}?ssl=require"


# Create the engine without running init
db_engine = create_async_engine(get_database_url(), echo=False)
