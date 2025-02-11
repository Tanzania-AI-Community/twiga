from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlmodel import text

import logging

from app.database.utils import get_database_url


logger = logging.getLogger(__name__)


# Create the engine without running init
db_engine = create_async_engine(
    get_database_url(),
    echo=False,
    pool_size=20,  # Adjust based on your concurrent users
    pool_pre_ping=True,  # Verify connections before usage
)

# Create a session factory
AsyncSessionLocal = async_sessionmaker(
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
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db() -> None:
    """Minimal database initialization"""
    try:
        async with db_engine.connect() as conn:
            await conn.scalar(text("SELECT 1"))
            logger.debug("Database connection verified")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
