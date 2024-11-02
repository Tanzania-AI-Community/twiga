from sqlmodel import SQLModel, Field, select, update
from sqlalchemy.ext.asyncio import AsyncSession
import logging
from datetime import datetime

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


class UserDatabaseError(Exception):
    """Base exception for user database operations"""

    pass


class UserUpdateError(UserDatabaseError):
    """Raised when user update fails"""

    pass


async def update_user_by_waid(user: User) -> User:
    """
    Update any information about an existing user and return the updated user.
    """
    if user is None:
        logger.error("Cannot update user: user object is None")
        raise UserUpdateError("Cannot update user: user object is None")

    # Convert the User object to a dictionary
    user_data = user.__dict__.copy()

    logger.debug(f"Updating user {user_data}")

    # Remove the _sa_instance_state attribute
    user_data.pop("_sa_instance_state", None)

    # Extract the wa_id
    wa_id = user_data.pop("wa_id")

    # Remove the id attribute
    user_data.pop("wa_id", None)
    user_data.pop("id", None)

    # Handle the birthday field if necessary
    if "birthday" in user_data and isinstance(user_data["birthday"], str):
        user_data["birthday"] = datetime.strptime(
            user_data["birthday"], "%Y-%m-%d"
        ).date()

    async with AsyncSession(db_engine) as session:
        try:
            statement = update(User).where(User.wa_id == wa_id).values(**user_data)
            await session.execute(statement)
            await session.commit()

            # Fetch the updated user
            result = await session.execute(select(User).filter_by(wa_id=wa_id))
            updated_user = result.scalar_one_or_none()

            logger.info(f"Updated user {wa_id} with {user_data}")
            return updated_user
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to update user {wa_id}: {str(e)}")
            raise UserUpdateError(f"Failed to update user: {str(e)}")


class UserQueryError(UserDatabaseError):
    """Raised when user query fails"""

    pass


async def get_user_data(wa_id: str) -> dict:
    """
    Retrieve user data based on wa_id.
    """
    async with AsyncSession(db_engine) as session:
        try:
            statement = select(User).where(User.wa_id == wa_id)
            result = await session.execute(statement)
            user = result.scalar_one_or_none()
            if user:
                user_data = user.model_dump()
                logger.info(f"Retrieved user data for {wa_id}: {user_data}")
                return user_data
            else:
                logger.warning(f"No user found with wa_id {wa_id}")
                return None
        except Exception as e:
            logger.error(f"Failed to query user {wa_id}: {str(e)}")
            raise UserQueryError(f"Failed to query user: {str(e)}")
