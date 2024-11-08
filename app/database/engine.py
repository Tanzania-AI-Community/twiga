from contextlib import asynccontextmanager
from urllib.parse import urlparse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlmodel import text
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.database.models import *
import logging


logger = logging.getLogger(__name__)


def get_database_url() -> str:
    """Get formatted database URL from settings"""
    database_uri = urlparse(settings.database_url.get_secret_value())
    return f"postgresql+asyncpg://{database_uri.username}:{database_uri.password}@{database_uri.hostname}{database_uri.path}?ssl=require"


# Create the engine without running init
db_engine = create_async_engine(
    get_database_url(),
    echo=False,
    pool_size=20,  # Adjust based on your concurrent users
    pool_pre_ping=True,  # Verify connections before usage
)

# Create a session factory
AsyncSessionLocal = sessionmaker(
    bind=db_engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Prevent lazy loading issues
)


@asynccontextmanager
async def get_session():
    """Provide a transactional scope around a series of operations."""
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db() -> None:
    """Minimal database initialization"""
    try:
        async with db_engine.connect() as conn:
            await conn.scalar(text("SELECT 1"))
            logger.info("Database connection verified")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
