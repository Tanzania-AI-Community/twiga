from typing import List, Optional
from sqlalchemy import text
from sqlmodel import select
import logging

from app.database.models import (
    User,
    Message,
    TeacherClass,
    Class,
    Chunk,
    Role,
    UserState,
    Subject,
    GradeLevel,
)
from app.database.engine import get_session
from app.utils import embedder

logger = logging.getLogger(__name__)

# TODO: Add custom Exceptions for better error handling


async def get_or_create_user(wa_id: str, name: Optional[str] = None) -> User:
    """
    Get existing user or create new one if they don't exist.
    Handles all database operations and error logging.
    """

    async with get_session() as session:
        try:
            # First try to get existing user
            statement = select(User).where(User.wa_id == wa_id).with_for_update()
            result = await session.execute(statement)
            user = result.scalar_one_or_none()

            if user:
                await session.refresh(user)
                return user

            # Create new user if they don't exist
            new_user = User(
                name=name,
                wa_id=wa_id,
                state=UserState.new,
                role=Role.teacher,
            )
            session.add(new_user)
            await session.flush()  # Get the ID without committing
            await session.refresh(new_user)

            logger.info(f"Created new user with wa_id: {wa_id}")
            return new_user

        except Exception as e:
            logger.error(f"Failed to get or create user for wa_id {wa_id}: {str(e)}")
            raise Exception(f"Failed to get or create user: {str(e)}")


async def get_user_by_waid(wa_id: str) -> Optional[User]:
    async with get_session() as session:
        try:
            statement = select(User).where(User.wa_id == wa_id)
            result = await session.execute(statement)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to query user {wa_id}: {str(e)}")
            raise Exception(f"Failed to query user: {str(e)}")


async def add_teacher_class(user: User, subject: Subject, grade: GradeLevel) -> Class:
    """
    Add a teacher-class to the teachers_classes table and update user's class_info

    Args:
        user: User object for the teacher
        subject: Subject enum value to find
        grade: GradeLevel enum value to find

    Returns:
        User: Updated user object

    """
    async with get_session() as session:
        try:
            # First check if the class exists
            statement = select(Class).where(
                Class.subject == subject, Class.grade_level == grade
            )
            result = await session.execute(statement)
            class_obj = result.scalar_one_or_none()

            # If class doesn't exist, create it
            if not class_obj:
                raise Exception(f"Class {subject} {grade} does not exist")

            # Check if teacher-class relationship already exists
            statement = select(TeacherClass).where(
                TeacherClass.teacher_id == user.id,
                TeacherClass.class_id == class_obj.id,
            )
            result = await session.execute(statement)
            teacher_class = result.scalar_one_or_none()

            # If relationship doesn't exist, create it
            if not teacher_class:
                teacher_class = TeacherClass(teacher_id=user.id, class_id=class_obj.id)
                session.add(teacher_class)
                await session.commit()

            # TODO: Consider updating user.class_info here too

            logger.info(f"Added class {subject} {grade} for user {user.id}")
            return class_obj

        except Exception as e:
            logger.error(f"Failed to add teacher class: {str(e)}")
            raise Exception(f"Failed to add teacher class: {str(e)}")


async def update_user(user: User) -> User:
    """
    Update any information about an existing user and return the updated user.

    Args:
        user (User): User object with updated information

    Returns:
        User: Updated user object

    """
    if user is None:
        logger.error("Cannot update user: user object is None")
        raise Exception("Cannot update user: user object is None")

    async with get_session() as session:
        try:
            # Add user to session and refresh to ensure we have latest data
            session.add(user)
            await session.commit()
            await session.refresh(user)

            logger.info(f"Updated user {user.wa_id}")
            return user

        except Exception as e:
            logger.error(f"Failed to update user {user.wa_id}: {str(e)}")
            raise Exception(f"Failed to update user: {str(e)}")


async def get_user_message_history(
    user_id: int, limit: int = 10
) -> Optional[List[Message]]:
    async with get_session() as session:
        try:
            # TODO: Make the database order this by default to reduce repeated operations
            statement = (
                select(Message)
                .where(Message.user_id == user_id)
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
            # query = text(
            #     """
            #     SELECT id, user_id, role, content, created_at
            #     FROM messages
            #     WHERE user_id = :user_id
            #     ORDER BY created_at DESC
            #     LIMIT :limit
            # """
            # )

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
    """Optimized bulk message creation"""
    if not messages:
        return []

    async with get_session() as session:
        try:
            # Add all messages to the session
            session.add_all(messages)
            await session.flush()  # Get IDs without committing
            return messages
        except Exception as e:
            logger.error(
                f"Unexpected error creating messages for user {messages[0].user_id}: {str(e)}"
            )
            raise Exception(f"Failed to create messages: {str(e)}")


async def create_new_message(message: Message) -> Message:
    """
    Create a single message in the database.
    """
    async with get_session() as session:
        try:
            # Add the message to the session
            session.add(message)

            # Commit the transaction
            await session.commit()

            # Refresh the message to get its ID and other DB-populated fields
            await session.refresh(message)

            return message

        except Exception as e:
            logger.error(f"Error creating message for user {message.user_id}: {str(e)}")
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

    async with get_session() as session:
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


async def get_user_resources(user: User) -> Optional[List[int]]:
    """
    Get all resource IDs accessible to a user through their class assignments.
    Uses a single optimized SQL query with proper indexing.

    Args:
        user_id: The ID of the user to find resources for

    Returns:
        List[int]: List of resource IDs the user has access to

    Raises:
        Exception: If there's an error querying the database
    """
    async with get_session() as session:
        try:
            # Use text() for a more efficient raw SQL query
            query = text(
                """
                SELECT DISTINCT cr.resource_id
                FROM teachers_classes tc
                JOIN classes_resources cr ON tc.class_id = cr.class_id
                WHERE tc.teacher_id = :user_id
            """
            )

            result = await session.execute(query, {"user_id": user.id})
            resource_ids = [row[0] for row in result.fetchall()]

            if not resource_ids:
                logger.warning(f"No resources found for user {user.wa_id}")
                return None

            logger.debug(f"Found resources {resource_ids} for user {user.wa_id}")
            return resource_ids

        except Exception as e:
            logger.error(f"Failed to get resources for user {user.wa_id}: {str(e)}")
            raise Exception(f"Failed to get user resources: {str(e)}")
