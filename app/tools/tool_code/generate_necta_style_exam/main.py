import logging
import json
from pathlib import Path

from app.database import db
from app.database.enums import ChunkType
from app.tools.tool_code.generate_necta_style_exam.exam_generator import (
    ExamGenerationError,
    ExamGenerator,
)

logger = logging.getLogger(__name__)


async def generate_necta_style_exam(
    class_id: int, subject: str, topics: list[str]
) -> str:
    """
    Generate a NECTA-style exam JSON.

    Flow:
    1. Retrieve topic chunks outside the exam generator.
    2. Call ExamGenerator with `chunks_by_topic` + `exam_spec`.
    3. Save `exam.json` and return metadata.

    Returns:
        A JSON string with path and generation metadata.
    """
    try:
        logger.info(
            "Generating NECTA-style exam for class_id=%s, subject=%s, topics=%s",
            class_id,
            subject,
            topics,
        )

        resource_ids = await db.get_class_resources(class_id)
        if not resource_ids:
            raise ExamGenerationError(f"No resources found for class_id={class_id}")

        chunks_by_topic = {}
        for topic in topics:
            topic_chunks = await db.vector_search(
                query=topic,
                n_results=10,
                where={
                    "chunk_type": [ChunkType.text],
                    "resource_id": resource_ids,
                },
            )
            chunks_by_topic[topic] = topic_chunks

        logger.info(
            "Retrieved chunks for topics: %s",
            {topic: len(chunks) for topic, chunks in chunks_by_topic.items()},
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

        logger.info("Exam specification: %s", exam_spec)

        generator = ExamGenerator()
        exam_json = await generator.generate_exam(
            subject=subject,
            chunks_by_topic=chunks_by_topic,
            exam_spec=exam_spec,
        )

        ##### Save exam JSON to file (for debug)
        output_dir = Path(__file__).parent / "output_tool"
        output_dir.mkdir(parents=True, exist_ok=True)
        exam_json_path = output_dir / "exam_test4.json"
        exam_json_path.write_text(
            json.dumps(exam_json, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return json.dumps(
            {
                "message": "Exam JSON generation successful.",
                "exam_json_path": str(exam_json_path),
                "subject": subject,
                "class_id": class_id,
                "topics": topics,
            },
            ensure_ascii=False,
        )

        """
        Here we should add the pdf generation
        """

        return "Exam JSON generation successful. Exam saved to: {}".format(
            exam_json_path
        )
    except ExamGenerationError as e:
        logger.error("Exam generation pipeline failed: %s", e, exc_info=True)
        raise Exception(f"Failed to generate Necta-style exam. Error: {str(e)}")
    except Exception as e:
        logger.error("Error in generate_necta_style_exam: %s", e, exc_info=True)
        raise Exception(f"Failed to generate Necta-style exam. Error: {str(e)}")
