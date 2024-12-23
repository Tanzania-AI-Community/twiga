from typing import Dict, List, Optional
from sqlalchemy import text
from sqlmodel import and_, select, or_, delete, insert, exists, desc
import logging
from sqlalchemy.orm import selectinload

from app.database.models import (
    User,
    Message,
    TeacherClass,
    Class,
    Chunk,
    Subject,
)
import app.database.enums as enums
from app.database.enums import SubjectClassStatus
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
                state=enums.UserState.new,
                role=enums.Role.teacher,
            )
            session.add(new_user)
            await session.flush()  # Get the ID without committing
            await session.commit()
            await session.refresh(new_user)
            logger.debug(f"Created new user with wa_id: {wa_id}")
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


async def update_user(user: User) -> User:
    """
    Update any information about an existing user and return the updated user.
    """
    async with get_session() as session:
        try:
            # Add user to session and refresh to ensure we have latest data
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.debug(f"Updated user {user.wa_id}: {user}")
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
                .order_by(desc(Message.created_at))
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
    """Optimized bulk message creation"""
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
            return list(result.scalars().all())
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


async def get_available_subjects() -> List[Subject]:
    """
    Get all available subjects with their IDs and names.

    Returns:
        List[Dict[str, str]]: List of dictionaries containing subject IDs and names as strings.
    """
    async with get_session() as session:
        try:
            # Apparently we can use .join(Subject.subject_classes) to get the classes as well
            statement = (
                select(Subject)
                .join(Class, Class.subject_id == Subject.id)  # type: ignore
                .where(Class.status == SubjectClassStatus.active)
                .distinct()
            )
            result = await session.execute(statement)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Failed to get available subjects: {str(e)}")
            raise Exception(f"Failed to get available subjects: {str(e)}")


# async def read_subject(subject_id: int) -> Optional[Subject]:
#     async with get_session() as session:
#         try:
#             statement = select(Subject).where(Subject.id == subject_id)
#             result = await session.execute(statement)
#             return result.scalar_one_or_none()
#         except Exception as e:
#             logger.error(f"Failed to read subject {subject_id}: {str(e)}")
#             raise Exception(f"Failed to read subject: {str(e)}")


async def read_subject(subject_id: int) -> Optional[Subject]:
    """
    Read a subject and its classes from the database.
    NOTE: This function uses eager loading so if you only need the subject object without classes loaded it might be better to make a new function
    """
    async with get_session() as session:
        try:
            # Use selectinload to eagerly load the subject_classes relationship
            statement = (
                select(Subject)
                .options(selectinload(Subject.subject_classes))  # type: ignore
                .where(Subject.id == subject_id)
            )
            result = await session.execute(statement)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to read subject {subject_id}: {str(e)}")
            raise Exception(f"Failed to read subject: {str(e)}")


async def read_classes(class_ids: List[int]) -> Optional[List[Class]]:
    async with get_session() as session:
        try:
            statement = select(Class).where(Class.id.in_(class_ids))  # type: ignore
            result = await session.execute(statement)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Failed to read classes {class_ids}: {str(e)}")
            raise Exception(f"Failed to read classes: {str(e)}")


async def get_class_ids_from_class_info(
    class_info: Dict[str, List[str]]
) -> Optional[List[int]]:
    """
    Get class IDs from a class_info dictionary structure in a single query

    Args:
        class_info: Dictionary mapping subject names to lists of grade levels
        Example: {"geography": ["os2"], "mathematics": ["os1", "os2"]}

    Returns:
        List of class IDs matching the subject-grade combinations
    """
    async with get_session() as session:
        # Build conditions for each subject and its grade levels
        conditions = [
            and_(Subject.name == subject_name, Class.grade_level.in_(grade_levels))  # type: ignore
            for subject_name, grade_levels in class_info.items()
        ]

        query = (
            select(Class.id)
            .join(Subject, Class.subject_id == Subject.id)  # type: ignore
            .where(or_(*conditions), Class.status == SubjectClassStatus.active)
        )

        result = await session.execute(query)
        if not result:
            logger.warning(f"No classes found for class info: {class_info}")
            return None

        return [row[0] for row in result]


async def assign_teacher_to_classes(
    user: User, class_ids: List[int], subject_id: Optional[int] = None
):
    """
    Assign a teacher to a list of classes by creating teacher-class relationships.
    If subject_id is provided, only replaces classes with that subject_id.
    Otherwise replaces all teacher-class relationships.
    """
    async with get_session() as session:
        try:
            # Construct delete query based on subject_id
            delete_query = delete(TeacherClass).where(
                TeacherClass.teacher_id == user.id  # type: ignore
            )

            if subject_id is not None:
                # Join with Class table to filter by subject_id
                delete_query = delete_query.where(
                    exists().where(
                        and_(
                            Class.id == TeacherClass.class_id,
                            Class.subject_id == subject_id,
                        )
                    )
                )

            # Delete existing relationships
            await session.execute(delete_query)

            # Bulk insert new relationships
            if class_ids:
                values = [
                    {"teacher_id": user.id, "class_id": class_id}
                    for class_id in class_ids
                ]
                await session.execute(insert(TeacherClass), values)
            else:
                logger.warning(f"No classes to assign for teacher {user.wa_id}")

        except Exception as e:
            logger.error(
                f"Failed to assign teacher {user.wa_id} to classes {class_ids}: {str(e)}"
            )
            raise Exception(f"Failed to assign teacher to classes: {str(e)}")
