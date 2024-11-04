from sqlmodel import SQLModel, Field, select, update
from sqlalchemy.ext.asyncio import AsyncSession
import logging
from datetime import datetime

from app.database.models import *
from app.database.engine import db_engine
from app.utils import embedder

logger = logging.getLogger(__name__)


class UserDatabaseError(Exception):
    """Base exception for user database operations"""

    pass


class UserCreationError(UserDatabaseError):
    """Raised when user creation fails"""

    pass


class MessageCreationError(UserDatabaseError):
    """Raised when message creation fails"""

    pass


class UserQueryError(UserDatabaseError):
    """Raised when user query fails"""

    pass


class UserUpdateError(UserDatabaseError):
    """Raised when user update fails"""

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


async def get_user_by_waid(wa_id: str) -> Optional[User]:
    async with AsyncSession(db_engine) as session:
        try:
            statement = select(User).where(User.wa_id == wa_id)
            result = await session.execute(statement)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to query user {wa_id}: {str(e)}")
            raise UserQueryError(f"Failed to query user: {str(e)}")


# async def update_user(user: User) -> User:
#     """
#     Update any information about an existing user and return the updated user.
#     """
#     if user is None:
#         logger.error("Cannot update user: user object is None")
#         raise UserUpdateError("Cannot update user: user object is None")

#     # Convert the User object to a dictionary
#     user_data = user.__dict__.copy()

#     logger.debug(f"Updating user {user_data}")

#     # Remove the _sa_instance_state attribute
#     user_data.pop("_sa_instance_state", None)

#     # Extract the wa_id
#     wa_id = user_data.pop("wa_id")

#     # Remove the id attribute
#     user_data.pop("wa_id", None)
#     user_data.pop("id", None)

#     # Handle the birthday field if necessary
#     if "birthday" in user_data and isinstance(user_data["birthday"], str):
#         user_data["birthday"] = datetime.strptime(
#             user_data["birthday"], "%Y-%m-%d"
#         ).date()

#     async with AsyncSession(db_engine) as session:
#         try:
#             statement = update(User).where(User.wa_id == wa_id).values(**user_data)
#             await session.execute(statement)
#             await session.commit()

#             # Fetch the updated user
#             result = await session.execute(select(User).filter_by(wa_id=wa_id))
#             updated_user = result.scalar_one_or_none()

#             logger.info(f"Updated user {wa_id} with {user_data}")
#             return updated_user
#         except Exception as e:
#             await session.rollback()
#             logger.error(f"Failed to update user {wa_id}: {str(e)}")
#             raise UserUpdateError(f"Failed to update user: {str(e)}")


async def add_teacher_class(user: User, subject: Subject, grade: GradeLevel) -> User:
    """
    Add a teacher-class to the teachers_classes table
    """
    pass


async def update_user(user: User) -> User:
    """
    Update any information about an existing user and return the updated user.

    Args:
        user (User): User object with updated information

    Returns:
        User: Updated user object

    Raises:
        UserUpdateError: If user is None or update fails
    """
    if user is None:
        logger.error("Cannot update user: user object is None")
        raise UserUpdateError("Cannot update user: user object is None")

    async with AsyncSession(db_engine) as session:
        try:
            # Add user to session and refresh to ensure we have latest data
            session.add(user)
            await session.commit()
            await session.refresh(user)

            logger.info(f"Updated user {user.wa_id}")
            return user

        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to update user {user.wa_id}: {str(e)}")
            raise UserUpdateError(f"Failed to update user: {str(e)}")


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


async def create_new_messages(messages: List[Message]) -> List[Message]:
    """
    Create multiple messages in the database in a single transaction.
    """
    if not messages:
        return []

    async with AsyncSession(db_engine) as session:
        try:
            # Add all messages to the session
            session.add_all(messages)

            # Commit the transaction
            await session.commit()

            # Refresh all messages to get their IDs and other DB-populated fields
            for message in messages:
                await session.refresh(message)

            return messages

        except Exception as e:
            await session.rollback()
            logger.error(
                f"Unexpected error creating messages for user {messages[0].user_id}: {str(e)}"
            )
            raise Exception(f"Failed to create messages: {str(e)}")


async def create_new_message(message: Message) -> Message:
    """
    Create a single message in the database.
    """
    try:
        messages = await create_new_messages([message])
        return messages[0]
    except UserCreationError as e:
        raise e
    except Exception as e:
        logger.error(f"Error in create_new_message: {str(e)}")
        raise Exception(f"Failed to create message: {str(e)}")


async def vector_search(query: str, n_results: int, where: dict) -> List[Chunk]:
    try:
        query_vector = embedder.get_embedding(query)
    except Exception as e:
        logger.error(f"Failed to get embedding for query {query}: {str(e)}")
        raise Exception(f"Failed to get embedding for query: {str(e)}")

    # Decode the where dict
    filters = []
    for key, value in where.items():
        if isinstance(value, list) and len(value) > 1:
            filters.append(getattr(Chunk, key).in_(value))
        elif isinstance(value, list) and len(value) == 1:
            filters.append(getattr(Chunk, key) == value[0])
        else:
            filters.append(getattr(Chunk, key) == value)

    async with AsyncSession(db_engine) as session:
        try:
            result = await session.execute(
                select(Chunk)
                .where(*filters)
                .order_by(Chunk.embedding.cosine_distance(query_vector))
                .limit(n_results)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Failed to search for knowledge: {str(e)}")
            raise Exception(f"Failed to search for knowledge: {str(e)}")
