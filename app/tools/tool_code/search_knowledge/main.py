import logging
from typing import Optional

import app.database.db as db
from app.database.db import vector_search
from app.database.enums import ChunkType
from app.database.models import Chunk, Resource

logger = logging.getLogger(__name__)


async def search_knowledge(
    search_phrase: str,
    class_id: int,
    subject: str | None = None,
) -> str:
    try:
        target_class_id = class_id

        if subject:
            normalized_subject = subject.strip().lower().replace(" ", "_")
            class_records = await db.read_classes([class_id])
            base_class = class_records[0] if class_records else None

            if normalized_subject and base_class:
                subject_record = await db.read_subject_by_name(normalized_subject)
                if subject_record:
                    subject_class = await db.read_class_by_subject_id_grade_level_and_status(
                        subject_id=subject_record.id,
                        grade_level=base_class.grade_level.value,
                        status=base_class.status.value,
                    )
                    if subject_class:
                        target_class_id = subject_class.id
                    else:
                        logger.warning(
                            "No class found for subject=%s and class_id=%s, falling back to class_id",
                            normalized_subject,
                            class_id,
                        )
                else:
                    logger.warning(
                        "Unknown subject=%s for search_knowledge, falling back to class_id=%s",
                        normalized_subject,
                        class_id,
                    )

        # Retrieve the resources for the class
        resource_ids = await db.get_class_resources(target_class_id)
        assert resource_ids

        # Retrieve the relevant content
        retrieved_content = await vector_search(
            query=search_phrase,
            n_results=10,
            where={
                "chunk_type": [ChunkType.text],
                "resource_id": resource_ids,
            },
        )
        logger.debug(
            f"Retrieved {len(retrieved_content)} content chunks, this is the first: {retrieved_content[0]}"
        )

        # Format the context and prompt
        return _format_context(retrieved_content)
    except Exception as e:
        logger.error(f"An error occurred when searching the knowledge base: {e}")
        raise Exception("Unable to search the course content. Skipping.")


def _format_context(
    retrieved_content: list[Chunk],
    resources: Optional[list[Resource]] = None,
) -> str:
    # Formatting the context
    context_parts = []
    if resources:
        resource_titles = ", ".join(
            [f"{resource.id}. {resource.name}" for resource in resources]
        )
        context_parts.append(f"### Context from the resources ({resource_titles})\n")

    for chunk in retrieved_content:
        if chunk.top_level_section_title:
            heading = f"-{str(chunk.chunk_type)} from section {chunk.top_level_section_title} in resource {chunk.resource_id}"
        else:
            heading = f"-{str(chunk.chunk_type)} from resource {chunk.resource_id}"
        context_parts.append(heading)
        context_parts.append(f"{chunk.content}")

    return str("\n".join(context_parts))
