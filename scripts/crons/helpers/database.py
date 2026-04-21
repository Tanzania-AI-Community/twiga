"""
Database helper functions for cron jobs.

This module provides database operations needed by cron jobs,
keeping the main cron scripts clean and focused.
"""

import os

# Import from app directory
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import and_, or_, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from app.database.enums import MessageRole, UserState
from app.database.models import Message, User

REMINDER_MESSAGE_TOOL_NAME = "user_inactivity_reminder"


def get_database_url() -> str:
    """
    Get formatted database URL from environment.

    Supports Neon.tech with SSL and standard PostgreSQL connections.

    Returns:
        str: Formatted asyncpg database URL

    Raises:
        SystemExit: If DATABASE_URL environment variable is not set
    """
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        print("ERROR: DATABASE_URL environment variable is required")
        sys.exit(1)

    database_uri = urlparse(database_url)

    # Add SSL for Neon.tech
    if database_uri.hostname and "neon.tech" in str(database_uri.hostname):
        return f"postgresql+asyncpg://{database_uri.username}:{database_uri.password}@{database_uri.hostname}{database_uri.path}?ssl=require"

    # Standard PostgreSQL connection
    return f"postgresql+asyncpg://{database_uri.username}:{database_uri.password}@{database_uri.hostname}:{database_uri.port}{database_uri.path}"


def create_db_engine(echo: bool = False, pool_size: int = 5):
    """
    Create database engine for cron jobs.

    Args:
        echo: Whether to log SQL statements
        pool_size: Number of connections in the pool

    Returns:
        AsyncEngine: Configured database engine
    """
    return create_async_engine(
        get_database_url(),
        echo=echo,
        pool_size=pool_size,
        pool_pre_ping=True,
    )


def create_session_maker(engine):
    """
    Create async session maker.

    Args:
        engine: Database engine

    Returns:
        async_sessionmaker: Configured session factory
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


# Global session maker (initialized by cron scripts)
_session_maker = None


def initialize_db(echo: bool = False, pool_size: int = 5):
    """
    Initialize database connection for cron jobs.

    Must be called before using database operations.

    Args:
        echo: Whether to log SQL statements
        pool_size: Number of connections in the pool
    """
    global _session_maker
    engine = create_db_engine(echo=echo, pool_size=pool_size)
    _session_maker = create_session_maker(engine)


@asynccontextmanager
async def get_session():
    """
    Provide a transactional database session.

    Yields:
        AsyncSession: Database session

    Raises:
        RuntimeError: If database not initialized
    """
    if _session_maker is None:
        raise RuntimeError("Database not initialized. Call initialize_db() first.")

    session = _session_maker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_users_by_state(state: UserState) -> list[User]:
    """
    Get all users with a specific state.

    Args:
        state: User state to filter by

    Returns:
        list[User]: Users with the specified state
    """
    async with get_session() as session:
        statement = select(User).where(User.state == state)
        result = await session.execute(statement)
        return list(result.scalars().all())


async def get_users_to_mark_inactive(hours_threshold: int) -> list[User]:
    """
    Get active users who should be marked as inactive.

    Finds users whose last_message_at is older than the threshold,
    or users who have never sent/received messages.

    Args:
        hours_threshold: Hours of inactivity before marking inactive

    Returns:
        list[User]: Users to mark as inactive
    """
    async with get_session() as session:
        # Calculate the threshold datetime
        threshold_time = datetime.utcnow() - timedelta(hours=hours_threshold)

        # Find active users whose last_message_at is older than threshold
        # OR users who have never sent/received messages (last_message_at is None)
        statement = select(User).where(
            and_(
                User.state == UserState.active,
                func.coalesce(
                    User.last_message_at,
                    text("'1970-01-01'::timestamp with time zone"),
                )
                < threshold_time,
            )
        )

        result = await session.execute(statement)
        return list(result.scalars().all())


async def get_users_for_reminder(
    inactivity_days: int,
    reminder_cooldown_days: int,
) -> list[User]:
    """
    Get users eligible for reminder messages.

    A user is eligible when:
    - Their state is active or inactive
    - They have a non-null last_message_at timestamp
    - Their last_message_at is older than inactivity_days
    - They have not received a reminder in the last reminder_cooldown_days

    Reminder messages are tracked by assistant messages with
    tool_name == "user_inactivity_reminder".
    """
    async with get_session() as session:
        inactivity_threshold = datetime.utcnow() - timedelta(days=inactivity_days)
        cooldown_threshold = datetime.utcnow() - timedelta(days=reminder_cooldown_days)

        reminder_history_subquery = (
            select(
                Message.user_id.label("user_id"),
                func.max(Message.created_at).label("last_reminder_at"),
            )
            .where(
                and_(
                    Message.role == MessageRole.assistant,
                    Message.tool_name == REMINDER_MESSAGE_TOOL_NAME,
                )
            )
            .group_by(Message.user_id)
            .subquery()
        )

        statement = (
            select(User)
            .outerjoin(
                reminder_history_subquery,
                User.id == reminder_history_subquery.c.user_id,
            )
            .where(
                and_(
                    User.state.in_([UserState.active, UserState.inactive]),  # type: ignore
                    User.last_message_at.is_not(None),
                    User.last_message_at < inactivity_threshold,
                    or_(
                        reminder_history_subquery.c.last_reminder_at.is_(None),
                        reminder_history_subquery.c.last_reminder_at
                        < cooldown_threshold,
                    ),
                )
            )
        )

        result = await session.execute(statement)
        return list(result.scalars().all())


async def update_user(user: User) -> User:
    """
    Update a user in the database.

    Args:
        user: User object to update

    Returns:
        User: Updated user object
    """
    async with get_session() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def create_message(message: Message) -> Message:
    """
    Create a new message in the database.

    Args:
        message: Message object to create

    Returns:
        Message: Created message object
    """
    async with get_session() as session:
        session.add(message)
        await session.commit()
        await session.refresh(message)
        return message
