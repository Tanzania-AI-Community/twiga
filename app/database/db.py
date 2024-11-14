from sqlalchemy import text
from sqlmodel import select
import logging
from datetime import datetime

from app.database.models import *
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
            logger.error(f"Database operation failed for wa_id {wa_id}: {str(e)}")
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


async def add_teacher_class(user: User, class_ids: List[int]) -> None:
    """
    Add a teacher-class to the teachers_classes table and update user's class_info

    Args:
        user: User object for the teacher
        class_ids: List of class IDs to add for the teacher

    Returns:
        None
    """
    async with get_session() as session:
        try:
            for class_id in class_ids:
                statement = select(TeacherClass).where(
                    TeacherClass.teacher_id == user.id,
                    TeacherClass.class_id == class_id,
                )
                result = await session.execute(statement)
                teacher_class = result.scalar_one_or_none()
                # Add teacher-class relationship if it doesn't exist
                if not teacher_class:
                    teacher_class = TeacherClass(teacher_id=user.id, class_id=class_id)
                    session.add(teacher_class)
            await session.commit()
            logger.info(f"Added classes {class_ids} for user {user.id}")
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

    # Ensure birthday is a date object
    if isinstance(user.birthday, str):
        try:
            user.birthday = datetime.strptime(user.birthday, "%Y-%m-%d").date()
        except ValueError as e:
            logger.error(f"Invalid date format for birthday: {user.birthday}")
            raise Exception(f"Invalid date format for birthday: {user.birthday}")

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
            # statement = (
            #     select(Message)
            #     .where(Message.user_id == user_id)
            #     .order_by(Message.created_at.desc())
            #     .limit(limit)
            # )
            query = text(
                """
                SELECT id, user_id, role, content, created_at
                FROM messages
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                LIMIT :limit
            """
            )

            result = await session.execute(query, {"user_id": user_id, "limit": limit})
            messages = result.fetchall()

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


async def get_available_subjects() -> List[Dict[str, str]]:
    """
    Get all available subjects with their IDs and names.

    Returns:
        List[Dict[str, str]]: List of dictionaries containing subject IDs and names as strings.
    """
    async with get_session() as session:
        try:
            statement = (
                select(Subject.id, Subject.name)
                .join(Class, Class.subject_id == Subject.id)
                .where(Class.status == SubjectClassStatus.active)
                .distinct()
            )
            result = await session.execute(statement)
            subjects = [
                {"id": str(row.id), "title": row.name} for row in result.fetchall()
            ]
            return subjects
        except Exception as e:
            logger.error(f"Failed to get available subjects: {str(e)}")
            raise Exception(f"Failed to get available subjects: {str(e)}")


async def get_subject_and_classes(subject_id: int) -> Dict[str, Any]:
    async with get_session() as session:
        try:
            statement = (
                select(
                    Subject.name.label("subject_name"),
                    Class.id,
                    Class.name,
                    Class.grade_level,
                )
                .join(Class, Class.subject_id == Subject.id)
                .where(Subject.id == subject_id)
            )
            result = await session.execute(statement)
            rows = result.fetchall()
            if not rows:
                raise Exception(
                    f"Subject with ID {subject_id} not found or has no classes"
                )

            subject_name = rows[0].subject_name
            classes = [
                {
                    "id": str(row.id),
                    "title": row.name,
                }
                for row in rows
            ]
            return {"subject_name": subject_name, "classes": classes}
        except Exception as e:
            logger.error(
                f"Failed to get subject and classes for subject ID {subject_id}: {str(e)}"
            )
            raise Exception(
                f"Failed to get subject and classes for subject ID: {str(e)}"
            )


async def generate_class_info(user: User) -> Dict[str, List[str]]:
    """
    Generate a JSON-like structure with subject names and class names based on user's selected class IDs.

    Args:
        user: User object

    Returns:
        Dict[str, List[str]]: Dictionary with subject names as keys and lists of class names as values
    """
    async with get_session() as session:
        try:
            logger.debug(f"Generating class info for user {user.wa_id}")
            # Fetch class details including subject names and class names
            statement = (
                select(
                    Class.id,
                    Class.name.label("class_name"),
                    Subject.name.label("subject_name"),
                )
                .join(Subject, Class.subject_id == Subject.id)
                .where(Class.id.in_(user.selected_class_ids))
            )
            result = await session.execute(statement)
            rows = result.fetchall()

            # Organize the data into a dictionary
            class_info = {}
            for row in rows:
                subject_name = row.subject_name
                class_name = row.class_name
                if subject_name not in class_info:
                    class_info[subject_name] = []
                class_info[subject_name].append(class_name)

            logger.debug(f"Generated class info for user {user.wa_id}: {class_info}")
            return class_info

        except Exception as e:
            logger.error(f"Failed to generate class info: {str(e)}")
            raise Exception(f"Failed to generate class info: {str(e)}")


async def add_default_subjects_and_classes() -> None:
    """
    Add a default subject called Geography with ID 1 and a class called Secondary Form 2 with ID 1.
    """
    async with get_session() as session:
        try:
            # Check if the default subject already exists with the correct ID and name
            statement = select(Subject).where(Subject.id == 1)
            result = await session.execute(statement)
            subject = result.scalar_one_or_none()

            if subject and subject.name != SubjectNames.geography.value:
                # Delete the existing subject with the incorrect name
                logger.info(f"Deleting existing subject with ID 1: {subject.name}")
                await session.delete(subject)
                await session.commit()
                subject = None

            if not subject:
                # Add the default subject
                default_subject = Subject(id=1, name=SubjectNames.geography.value)
                session.add(default_subject)
                await session.commit()
                logger.info(f"Added default subject: {SubjectNames.geography.value}")

            # Check if the default class already exists with the correct ID and grade level
            statement = select(Class).where(Class.id == 1)
            result = await session.execute(statement)
            class_ = result.scalar_one_or_none()

            if class_ and class_.grade_level != GradeLevel.os2:
                # Delete the existing class with the incorrect grade level
                await session.delete(class_)
                await session.commit()
                class_ = None

            if not class_:
                # Add the default class
                default_class = Class(
                    id=1,
                    name="Secondary Form 2",
                    subject_id=1,
                    grade_level=GradeLevel.os2,
                    status=SubjectClassStatus.active,
                )
                session.add(default_class)
                await session.commit()
                logger.info("Added default class: Secondary Form 2")

        except Exception as e:
            logger.error(f"Failed to add default subjects and classes: {str(e)}")
            raise Exception(f"Failed to add default subjects and classes: {str(e)}")


async def update_user_selected_classes(
    user: User, selected_classes: List[int], subject_id: int
) -> User:
    """
    Update the user's classes for a given subject according to the new selected classes.

    Args:
        user: User object to update
        selected_classes: List of class IDs selected by the user
        subject_id: ID of the subject to update classes for

    Returns:
        User: Updated user object
    """
    async with get_session() as session:
        try:
            logger.debug(
                f"Updating user {user.wa_id} with new classes: {selected_classes} for subject ID: {subject_id}"
            )

            # Fetch all class IDs for the given subject ID
            statement = select(Class.id).where(Class.subject_id == subject_id)
            result = await session.execute(statement)
            subject_class_ids = [row[0] for row in result.fetchall()]
            logger.debug(f"Class IDs for subject ID {subject_id}: {subject_class_ids}")

            # Filter the user's selected classes to only include those not related to the subject
            new_class_ids = [
                class_id
                for class_id in user.selected_class_ids or []
                if class_id not in subject_class_ids
            ]
            logger.debug(
                f"Filtered class IDs not related to subject ID {subject_id}: {new_class_ids}"
            )

            # Add the new selected classes for the subject
            new_class_ids.extend(selected_classes)
            logger.debug(
                f"New class IDs after adding selected classes: {new_class_ids}"
            )

            # Remove duplicates if any
            new_class_ids = list(set(new_class_ids))
            logger.debug(f"Final class IDs after removing duplicates: {new_class_ids}")

            # Update the user's selected classes
            user.selected_class_ids = new_class_ids
            logger.debug(
                f"User's selected class IDs updated to: {user.selected_class_ids}"
            )

            logger.debug(f"HERE HERHER ERHHRE HERE WITH USER User : {user}")

            # Update the user state to active if it's not already
            if user.state != "active":
                user.state = "active"
                logger.debug(f"User state updated to: {user.state}")

            # Update the user onboarding state to completed if it's not already
            if user.onboarding_state != "completed":
                user.onboarding_state = "completed"
                logger.debug(
                    f"User onboarding state updated to: {user.onboarding_state}"
                )

            logger.debug(f"FINISHED UPDATING USER User : {user}")

            # Update the user's class info
            logger.debug("Generating class info for the user")
            user.class_info = await generate_class_info(user)

            logger.debug("FINISHED GENERATING CLASS INFO")

            user = await update_user(user)
            logger.debug(f"User {user.wa_id} updated in the database")

            formatted_selected_classes = [int(class_id) for class_id in new_class_ids]
            await add_teacher_class(user, formatted_selected_classes)
            logger.debug(f"Teacher-class relationships updated for user {user.wa_id}")

            logger.info(
                f"Updated user {user.wa_id} with new classes for subject ID {subject_id}"
            )

            return user
        except Exception as e:
            logger.error(f"Failed to update user subject classes: {str(e)}")
            raise Exception(f"Failed to update user subject classes: {str(e)}")
