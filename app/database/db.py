from sqlmodel import SQLModel, Field, select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.database.models import *
from app.database.engine import db_engine

logger = logging.getLogger(__name__)


class UserDatabaseError(Exception):
    """Base exception for user database operations"""

    pass


class UserCreationError(UserDatabaseError):
    """Raised when user creation fails"""

    pass


class UserQueryError(UserDatabaseError):
    """Raised when user query fails"""

    pass


async def get_or_create_user(wa_id: str, name: Optional[str] = None) -> User:
    """
    Get existing user or create new one if they don't exist.
    Handles all database operations and error logging.
    """

    async with AsyncSession(db_engine) as session:
        try:
            # First try to get existing user
            statement = select(User).where(User.wa_id == wa_id)
            result = await session.execute(statement)
            user = result.scalar_one_or_none()

            if user:
                return user

            # Create new user if they don't exist
            new_user = User(
                name=name,
                wa_id=wa_id,
                state=UserState.new,
                role=Role.teacher,
            )
            session.add(new_user)
            await session.commit()
            await session.refresh(new_user)

            logger.info(f"Created new user with wa_id: {wa_id}")
            return new_user

        except Exception as e:
            await session.rollback()
            logger.error(f"Database operation failed for wa_id {wa_id}: {str(e)}")
            raise UserDatabaseError(f"Failed to get or create user: {str(e)}")


async def create_new_user(name: Optional[str], wa_id: str) -> User:
    """Create new user explicitly"""
    async with AsyncSession(db_engine) as session:
        try:
            new_user = User(
                name=name,
                wa_id=wa_id,
                state=UserState.new,
                role=Role.teacher,
            )
            session.add(new_user)
            await session.commit()
            await session.refresh(new_user)
            return new_user
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to create user {wa_id}: {str(e)}")
            raise UserCreationError(f"Failed to create user: {str(e)}")


async def get_user_by_waid(wa_id: str) -> Optional[User]:
    async with AsyncSession(db_engine) as session:
        try:
            statement = select(User).where(User.wa_id == wa_id)
            result = await session.execute(statement)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to query user {wa_id}: {str(e)}")
            raise UserQueryError(f"Failed to query user: {str(e)}")


async def get_user_message_history(
    user_id: int, limit: int = 10
) -> Optional[List[Message]]:
    async with AsyncSession(db_engine) as session:
        try:
            # TODO: Make the database order this by default to reduce repeated operations
            statement = (
                select(Message)
                .where(Message.user_id == user_id)
                .order_by(Message.created_at.desc())
                .limit(limit)
            )

            result = await session.execute(statement)
            messages = result.scalars().all()

            # If no messages found, return empty list
            if not messages:
                logger.debug(f"No message history found for user {user_id}")
                return None

            # Convert to list and reverse to get chronological order (oldest first)
            return list(reversed(messages))

        except Exception as e:
            logger.error(
                f"Failed to retrieve message history for user {user_id}: {str(e)}"
            )
            raise Exception(f"Failed to retrieve message history: {str(e)}")
