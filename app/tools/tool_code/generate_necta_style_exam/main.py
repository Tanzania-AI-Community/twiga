import json
import logging
from datetime import datetime, timedelta, timezone

import app.database.db as db
from app.config import settings
from app.database.db import create_new_exam
from app.database.enums import ChunkType
from app.tools.tool_code.generate_necta_style_exam.exam_generator import (
    ExamGenerationError,
    exam_generator,
)
from app.utils.string_manager import StringCategory, strings

NUM_CHUNKS_PER_TOPIC = 25
logger = logging.getLogger(__name__)


async def generate_necta_style_exam(
    class_id: int, subject: str, topics: list[str], user_id: int
) -> str:
    """
    Generate a NECTA-style exam JSON.

    Flow:
    1. Retrieve topic chunks outside the exam generator.
    2. Call exam_generator with `chunks_by_topic` + `exam_spec`.
    3. Save `exam.json` and return metadata.

    Returns:
        A JSON string with success message and generation metadata.
    """
    try:
        logger.info(
            f"Generating NECTA-style exam for user_id={user_id}, class_id={class_id}, subject={subject}, topics={topics}"
        )

        window_start = datetime.now(timezone.utc) - timedelta(
            days=settings.exam_generation_window_days
        )
        if (
            await db.count_generated_exams_since(user_id, window_start)
            >= settings.exam_generation_limit
        ):
            tool_strings = strings.get_category(StringCategory.TOOLS)
            message = tool_strings["generate_necta_style_exam"]["rate_limited"].format(
                limit=settings.exam_generation_limit,
                window_days=settings.exam_generation_window_days,
            )
            return json.dumps(
                {
                    "status": "rate_limited",
                    "message": message,
                    "limit": settings.exam_generation_limit,
                    "window_days": settings.exam_generation_window_days,
                },
                ensure_ascii=False,
            )

        resource_ids = await db.get_class_resources(class_id)
        if not resource_ids:
            raise ExamGenerationError(f"No resources found for class_id={class_id}")

        chunks_by_topic = {}
        for topic in topics:
            topic_chunks = await db.vector_search(
                query=topic,
                n_results=NUM_CHUNKS_PER_TOPIC,
                where={
                    "chunk_type": [ChunkType.text],
                    "resource_id": resource_ids,
                },
            )
            chunks_by_topic[topic] = topic_chunks

        logger.info(
            f"Retrieved chunks for topics: { {topic: len(chunks) for topic, chunks in chunks_by_topic.items()} }"
        )

        exam_spec = {
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

        logger.info(f"Exam specification: {exam_spec}")

        exam_json = await exam_generator.generate_exam(
            subject=subject,
            chunks_by_topic=chunks_by_topic,
            exam_spec=exam_spec,
        )

        generation_trace = exam_json.get("generation_trace", {})
        exam_id = generation_trace.get("exam_id")
        if not exam_id:
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

        return json.dumps(
            {
                "message": "Exam generation successful.",
                "exam_id": exam_id,
                "subject": subject,
                "class_id": class_id,
                "topics": topics,
            },
            ensure_ascii=False,
        )
    except ExamGenerationError as e:
        logger.error(f"Exam generation pipeline failed: {e}", exc_info=True)
        raise Exception(f"Failed to generate Necta-style exam. Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error in generate_necta_style_exam: {e}", exc_info=True)
        raise Exception(f"Failed to generate Necta-style exam. Error: {str(e)}")
