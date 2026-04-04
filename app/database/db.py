import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import selectinload
from sqlmodel import and_, delete, desc, exists, insert, or_, select

import app.database.enums as enums
from app.database.engine import get_session
from app.database.enums import SubjectClassStatus
from app.database.models import (
    Chunk,
    Class,
    ClassResource,
    GeneratedExam,
    Message,
    Resource,
    Subject,
    TeacherClass,
    User,
)
from app.utils import embedder

logger = logging.getLogger(__name__)

# TODO: Add custom Exceptions for better error handling


def _parse_generated_at_utc(exam_json: dict) -> datetime | None:
    generation_trace = exam_json.get("generation_trace", {})
    generated_at_raw = generation_trace.get("generated_at_utc")

    if not isinstance(generated_at_raw, str) or not generated_at_raw.strip():
        return None

    timestamp = generated_at_raw.strip()
    if timestamp.endswith("Z"):
        timestamp = f"{timestamp[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        logger.warning(
            "Invalid generation_trace.generated_at_utc for exam_id=%s: %s",
            generation_trace.get("exam_id"),
            generated_at_raw,
        )
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def create_new_exam(
    exam_json: dict,
    class_id: int,
    subject: str,
    topics: list[str],
    user_id: int,
) -> GeneratedExam:
    generation_trace = exam_json.get("generation_trace", {})
    exam_id = generation_trace.get("exam_id")

    normalized_exam_id = exam_id.strip() if isinstance(exam_id, str) else None
    if not normalized_exam_id:
        raise ValueError(
            "Missing generation_trace.exam_id in exam JSON; cannot persist generated exam."
        )

    if not isinstance(class_id, int):
        raise ValueError("class_id must be an integer.")

    normalized_subject = subject.strip() if isinstance(subject, str) else None
    if not normalized_subject:
        raise ValueError("subject must be a non-empty string.")

    normalized_topics = [
        topic.strip() for topic in topics if isinstance(topic, str) and topic.strip()
    ]
    if not normalized_topics:
        raise ValueError("topics must contain at least one non-empty string.")

    if not isinstance(user_id, int):
        raise ValueError("user_id must be an integer.")

    generated_at_utc = _parse_generated_at_utc(exam_json)

    async with get_session() as session:
        try:
            statement = select(GeneratedExam).where(
                GeneratedExam.id == normalized_exam_id
            )
            result = await session.execute(statement)
            existing_exam = result.scalar_one_or_none()
            if existing_exam is not None:
                raise ValueError(
                    f"Exam with exam_id={normalized_exam_id} already exists."
                )

            generated_exam = GeneratedExam(
                id=normalized_exam_id,
                exam_json=exam_json,
                user_id=user_id,
                class_id=class_id,
                subject=normalized_subject,
                topics=normalized_topics,
                generated_at_utc=generated_at_utc,
            )

            session.add(generated_exam)
            await session.flush()
            return generated_exam
        except Exception as e:
            logger.error(
                "Failed to create generated exam %s: %s",
                normalized_exam_id,
                str(e),
            )
            raise Exception(f"Failed to create generated exam: {str(e)}")


async def get_exam(exam_id: str) -> GeneratedExam | None:
    if not isinstance(exam_id, str) or not exam_id.strip():
        raise ValueError("exam_id must be a non-empty string.")

    normalized_exam_id = exam_id.strip()

    async with get_session() as session:
        try:
            statement = select(GeneratedExam).where(
                GeneratedExam.id == normalized_exam_id
            )
            result = await session.execute(statement)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error("Failed to retrieve exam %s: %s", normalized_exam_id, str(e))
            raise Exception(f"Failed to retrieve exam: {str(e)}")


async def get_user_by_waid(wa_id: str) -> User | None:
    """
    Get user by WhatsApp ID with FULL class hierarchy loaded.
    Always loads: User -> taught_classes -> class_ -> subject_

    This is the ONLY method to fetch users - it loads everything needed.
    All data is loaded while the session is open, then returned from memory.
    """
    async with get_session() as session:
        try:
            # Eagerly load full relationship chain: User -> TeacherClass -> Class -> Subject
            statement = (
                select(User)
                .where(User.wa_id == wa_id)
                .options(
                    selectinload(User.taught_classes)  # type: ignore
                    .selectinload(TeacherClass.class_)  # type: ignore
                    .selectinload(Class.subject_)  # type: ignore
                )
            )
            result = await session.execute(statement)
            user = result.scalar_one_or_none()

            # Access relationships to trigger loading while session is still open
            if user and user.taught_classes:
                for tc in user.taught_classes:
                    # Access attributes to ensure they're loaded
                    _ = tc.class_id
                    _ = tc.teacher_id

            return user
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
) -> list[Message] | None:
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


async def get_latest_user_message_by_role(
    user_id: int, role: enums.MessageRole
) -> Message | None:
    async with get_session() as session:
        try:
            statement = (
                select(Message)
                .where(and_(Message.user_id == user_id, Message.role == role))
                .order_by(desc(Message.created_at))
                .limit(1)
            )
            result = await session.execute(statement)
            return result.scalars().first()
        except Exception as e:
            logger.error(
                f"Failed to retrieve latest {role.value} message for user {user_id}: {str(e)}"
            )
            raise Exception(f"Failed to retrieve latest message: {str(e)}")


async def create_new_messages(messages: list[Message]) -> list[Message]:
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
    Create a single message in the database and update user's last_message_at.
    """
    from datetime import datetime, timezone

    async with get_session() as session:
        try:
            # Add the message to the session
            session.add(message)

            # Update user's last_message_at timestamp
            if message.user_id:
                user_statement = select(User).where(User.id == message.user_id)
                user_result = await session.execute(user_statement)
                user = user_result.scalar_one_or_none()
                if user:
                    user.last_message_at = datetime.now(timezone.utc)
                    session.add(user)

            # Commit the transaction
            await session.commit()

            # Refresh the message to get its ID and other DB-populated fields
            await session.refresh(message)

            return message

        except Exception as e:
            logger.error(f"Error creating message for user {message.user_id}: {str(e)}")
            raise Exception(f"Failed to create message: {str(e)}")


async def create_new_message_by_fields(
    *,
    user_id: int,
    role: enums.MessageRole,
    content: str | None = None,
    source_chunk_ids: list[int] | None = None,
    is_present_in_conversation: bool = False,
    tool_calls: list[dict] | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
) -> Message:
    message = Message(
        user_id=user_id,
        role=role,
        content=content,
        source_chunk_ids=source_chunk_ids,
        is_present_in_conversation=is_present_in_conversation,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
    )
    return await create_new_message(message)


async def vector_search(query: str, n_results: int, where: dict) -> list[Chunk]:
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


async def read_subjects() -> list[Subject] | None:
    """
    Read all subject and its classes from the database.
    NOTE: This function uses eager loading so if you only need the subject object without classes loaded it might be better to make a new function
    """
    async with get_session() as session:
        try:
            # Use selectinload to eagerly load the subject_classes relationship
            statement = select(Subject).options(
                selectinload(Subject.subject_classes)  # type: ignore
            )  # type: ignore
            result = await session.execute(statement)
            return list(result.scalars().all())
        except Exception as e:
            raise Exception(f"Failed to read subjects: {str(e)}")


async def get_class_resources(class_id: int) -> list[int] | None:
    """
    Get all resource IDs accessible to a class.
    Uses a single optimized SQL query with proper indexing.
    """
    async with get_session() as session:
        try:
            # Use text() for a more efficient raw SQL query
            query = text(
                """
                SELECT DISTINCT resource_id
                FROM classes_resources
                WHERE class_id = :class_id
                """
            )

            result = await session.execute(query, {"class_id": class_id})
            resource_ids = [row[0] for row in result.fetchall()]

            if not resource_ids:
                logger.warning(f"No resources found for class {class_id}")
                return None

            logger.debug(f"Found resources {resource_ids} for class {class_id}")
            return resource_ids

        except Exception as e:
            logger.error(f"Failed to get resources for class {class_id}: {str(e)}")
            raise Exception(f"Failed to get class resources: {str(e)}")


async def get_user_resources(user: User) -> list[int] | None:
    """
    Get all resource IDs accessible to a user through their class assignments.
    Uses a single optimized SQL query with proper indexing.

    Args:
        user_id: The ID of the user to find resources for

    Returns:
        list[int]: List of resource IDs the user has access to

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


# async def read_subject(subject_id: int) -> Subject | None:
#     async with get_session() as session:
#         try:
#             statement = select(Subject).where(Subject.id == subject_id)
#             result = await session.execute(statement)
#             return result.scalar_one_or_none()
#         except Exception as e:
#             logger.error(f"Failed to read subject {subject_id}: {str(e)}")
#             raise Exception(f"Failed to read subject: {str(e)}")


async def read_subject(subject_id: int) -> Subject | None:
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


async def read_subject_by_name(subject_name: str) -> Subject | None:
    async with get_session() as session:
        try:
            # Use selectinload to eagerly load the subject_classes relationship
            statement = (
                select(Subject)
                .options(selectinload(Subject.subject_classes))  # type: ignore
                .where(Subject.name == subject_name)
            )
            result = await session.execute(statement)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to read subject {subject_name}: {str(e)}")
            raise Exception(f"Failed to read subject: {str(e)}")


async def read_resource_by_name(resource_name: str) -> Resource | None:
    async with get_session() as session:
        try:
            # Use selectinload to eagerly load the subject_classes relationship
            statement = select(Resource).where(Resource.name == resource_name)
            result = await session.execute(statement)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to read resource {resource_name}: {str(e)}")
            raise Exception(f"Failed to read resource: {str(e)}")


async def read_class_by_subject_id_grade_level_and_status(
    subject_id: int,
    grade_level: str,
    status: str,
) -> Class | None:
    async with get_session() as session:
        filters = [
            Class.grade_level == enums.GradeLevel(grade_level),
            Class.status == SubjectClassStatus(status),
            Class.subject_id == subject_id,
        ]

        try:
            # Use selectinload to eagerly load the subject_classes relationship
            statement = (
                select(Class)
                # .options(selectinload(Subject.subject_classes))  # type: ignore
                .where(*filters)
            )
            result = await session.execute(statement)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(
                f"Failed to read class from subject_id={subject_id}, grade_level={grade_level} and status={status}: {str(e)}"
            )
            raise Exception(f"Failed to read subject: {str(e)}")


async def does_class_resource_rel_exist(class_id: int, resource_id: int) -> bool:
    async with get_session() as session:
        filters = [
            ClassResource.class_id == class_id,
            ClassResource.resource_id == resource_id,
        ]

        try:
            # Use selectinload to eagerly load the subject_classes relationship
            statement = select(ClassResource).where(*filters)
            result = await session.execute(statement)
            return result.scalar_one_or_none() is not None

        except Exception as e:
            logger.error(
                f"Failed to verify relation from class_id={class_id} and resource_id={resource_id}: {str(e)}"
            )
            raise Exception(f"Failed to read relation: {str(e)}")


async def read_classes(class_ids: list[int]) -> list[Class] | None:
    async with get_session() as session:
        try:
            statement = select(Class).where(Class.id.in_(class_ids))  # type: ignore
            result = await session.execute(statement)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Failed to read classes {class_ids}: {str(e)}")
            raise Exception(f"Failed to read classes: {str(e)}")


async def get_class_ids_from_class_info(
    class_info: dict[str, list[str]],
) -> list[int] | None:
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
    user: User, class_ids: list[int], subject_id: int | None = None
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


async def get_users_by_state(state: enums.UserState) -> list[User]:
    """
    Get all users with a specific state.

    Args:
        state: The UserState to filter by

    Returns:
        list[User]: List of users with the specified state
    """
    async with get_session() as session:
        try:
            # Simple load without full class hierarchy
            statement = select(User).where(User.state == state)
            result = await session.execute(statement)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Failed to query users by state {state}: {str(e)}")
            raise Exception(f"Failed to query users by state: {str(e)}")


async def get_users_to_mark_inactive(hours_threshold: int) -> list[User]:
    """
    Get active users who haven't sent or received messages in the specified hours.

    Args:
        hours_threshold: Number of hours after which a user is considered inactive

    Returns:
        list[User]: List of active users who should be marked as inactive
    """
    from datetime import datetime, timedelta, timezone

    async with get_session() as session:
        try:
            # Calculate the threshold datetime
            threshold_time = datetime.now(timezone.utc) - timedelta(
                hours=hours_threshold
            )

            # Find active users whose last_message_at is older than threshold
            # OR users who have never sent/received messages (last_message_at is None)
            from sqlalchemy import func

            statement = select(User).where(
                and_(
                    User.state == enums.UserState.active,
                    func.coalesce(
                        User.last_message_at,
                        text("'1970-01-01'::timestamp with time zone"),
                    )
                    < threshold_time,
                )
            )

            result = await session.execute(statement)
            return list(result.scalars().all())

        except Exception as e:
            logger.error(
                f"Failed to query inactive users with threshold {hours_threshold}h: {str(e)}"
            )
            raise Exception(f"Failed to query inactive users: {str(e)}")
