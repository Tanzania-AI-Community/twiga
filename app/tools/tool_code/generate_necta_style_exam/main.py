import json
import logging
from datetime import datetime, timedelta, timezone

import app.database.db as db
from app.config import settings
from app.database.db import create_new_exam
from app.database.enums import ChunkType
from app.services.exam_quota_service import (
    QuotaDecision,
    QuotaOutcome,
    exam_quota_service,
    exam_request_key,
)
from app.tools.tool_code.generate_necta_style_exam.exam_generator import (
    ExamGenerationError,
    exam_generator,
)
from app.utils.string_manager import StringCategory, strings

NUM_CHUNKS_PER_TOPIC = 25
# Tanzania keeps UTC+3 all year (no daylight saving)
EAST_AFRICA_TIME = timezone(timedelta(hours=3), "EAT")
logger = logging.getLogger(__name__)


async def generate_necta_style_exam(
    class_id: int, subject: str, topics: list[str], user_id: int
) -> str:
    """
    Generate a NECTA-style exam JSON.

    Flow:
    1. Reserve a slot under the user's exam limit (or reuse the same recent exam).
    2. Retrieve topic chunks outside the exam generator.
    3. Call exam_generator with `chunks_by_topic` + `exam_spec`.
    4. Save `exam.json` and return metadata.

    Returns:
        A JSON string with success message and generation metadata.
    """
    try:
        logger.info(
            f"Generating NECTA-style exam for user_id={user_id}, class_id={class_id}, subject={subject}, topics={topics}"
        )

        decision = await exam_quota_service.reserve(
            user_id, exam_request_key(class_id, subject, topics)
        )
        payload = _payload_without_generating(decision, class_id, subject, topics)
        if payload is not None:
            return payload

        try:
            exam_id = await _generate_and_save_exam(class_id, subject, topics, user_id)
        except Exception:
            await exam_quota_service.release(decision.reservation_id)
            raise
        await exam_quota_service.complete(decision.reservation_id, exam_id)

        return _success_payload(exam_id, subject, class_id, topics)
    except ExamGenerationError as e:
        logger.error(f"Exam generation pipeline failed: {e}", exc_info=True)
        raise Exception(f"Failed to generate Necta-style exam. Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error in generate_necta_style_exam: {e}", exc_info=True)
        raise Exception(f"Failed to generate Necta-style exam. Error: {str(e)}")


async def preflight_necta_style_exam(
    class_id: int, subject: str, topics: list[str], user_id: int
) -> str | None:
    """Answer at once, before the "takes 10 minutes" notice, when no exam will be generated.

    Read-only: generate_necta_style_exam's reserve() stays the real check.
    """
    decision = await exam_quota_service.preview(
        user_id, exam_request_key(class_id, subject, topics)
    )
    return _payload_without_generating(decision, class_id, subject, topics)


def _payload_without_generating(
    decision: QuotaDecision, class_id: int, subject: str, topics: list[str]
) -> str | None:
    """The tool result for a decision that needs no new exam, else None."""
    match decision.outcome:
        case QuotaOutcome.REUSE:
            logger.info(f"Reusing exam_id={decision.exam_id} for a repeated request")
            return _success_payload(
                decision.exam_id, subject, class_id, topics, reused=True
            )
        case QuotaOutcome.IN_PROGRESS:
            return _error_payload("exam_in_progress", _tool_string("in_progress"))
        case QuotaOutcome.DENIED:
            return _limit_reached_payload(decision.next_available_at)
    return None


async def _generate_and_save_exam(
    class_id: int, subject: str, topics: list[str], user_id: int
) -> str:
    """Run retrieval and generation, save the exam, and return its id."""
    chunks_by_topic = await _retrieve_chunks(class_id, topics)

    exam_spec = _build_exam_spec()
    logger.info(f"Exam specification: {exam_spec}")

    exam_json = await exam_generator.generate_exam(
        subject=subject,
        chunks_by_topic=chunks_by_topic,
        exam_spec=exam_spec,
    )

    if not exam_json.get("generation_trace", {}).get("exam_id"):
        raise ExamGenerationError(
            "Missing generation_trace.exam_id in exam JSON; cannot persist exam."
        )

    persisted_exam_record = await create_new_exam(
        exam_json=exam_json,
        class_id=class_id,
        subject=subject,
        topics=topics,
        user_id=user_id,
    )
    logger.info(f"Persisted generated exam with exam_id={persisted_exam_record.id}")
    return persisted_exam_record.id


async def _retrieve_chunks(class_id: int, topics: list[str]) -> dict[str, list]:
    resource_ids = await db.get_class_resources(class_id)
    if not resource_ids:
        raise ExamGenerationError(f"No resources found for class_id={class_id}")

    chunks_by_topic = {}
    for topic in topics:
        chunks_by_topic[topic] = await db.vector_search(
            query=topic,
            n_results=NUM_CHUNKS_PER_TOPIC,
            where={
                "chunk_type": [ChunkType.text],
                "resource_id": resource_ids,
            },
        )

    logger.info(
        f"Retrieved chunks for topics: { {topic: len(chunks) for topic, chunks in chunks_by_topic.items()} }"
    )
    return chunks_by_topic


def _build_exam_spec() -> dict:
    return {
        "meta": {
            "exam_title": "GENERATED PRACTICE EXAM",
            "duration": "3:00 Hrs",
        },
        "sections": {
            "A": {
                "multiple_choice_marks": 10,
                "matching_marks": 5,
                "num_mcq_items": 10,
                "num_matching_questions": 1,
            },
            "B": {
                "marks": 70,
                "num_short_answer_questions": 5,
            },
            "C": {
                "marks": 15,
                "num_long_answer_questions": 2,
            },
        },
        "default_difficulty": "medium",
    }


def _tool_string(key: str) -> str:
    return strings.get_category(StringCategory.TOOLS)["generate_necta_style_exam"][key]


def _success_payload(
    exam_id: str,
    subject: str,
    class_id: int,
    topics: list[str],
    reused: bool = False,
) -> str:
    payload = {
        "message": "Exam generation successful.",
        "exam_id": exam_id,
        "subject": subject,
        "class_id": class_id,
        "topics": topics,
    }
    if reused:
        payload["reused"] = True
    return json.dumps(payload, ensure_ascii=False)


def _error_payload(error_code: str, message: str, **details) -> str:
    """A result the agent relays as written (see the tool description)."""
    return json.dumps(
        {"error": message, "error_code": error_code, **details}, ensure_ascii=False
    )


def _limit_reached_payload(next_available_at: datetime) -> str:
    local_time = next_available_at.astimezone(EAST_AFRICA_TIME)
    message = _tool_string("rate_limited").format(
        limit=settings.exam_generation_limit,
        window_days=settings.exam_generation_window_days,
        next_available_date=(
            f"{local_time:%A} {local_time.day} {local_time:%B}, {local_time:%H:%M} EAT"
        ),
    )
    return _error_payload(
        "exam_limit_reached",
        message,
        limit=settings.exam_generation_limit,
        window_days=settings.exam_generation_window_days,
        next_available_at=local_time.isoformat(timespec="minutes"),
    )
