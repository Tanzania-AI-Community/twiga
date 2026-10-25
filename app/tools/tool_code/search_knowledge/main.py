import logging
from typing import Optional, TypedDict

import app.database.db as db
from app.config import tool_settings
from app.database.db import vector_search
from app.database.enums import ChunkType
from app.database.models import Chunk, Resource

logger = logging.getLogger(__name__)


class SearchKnowledgeResult(TypedDict):
    content: str
    source_chunk_ids: list[int]


async def search_knowledge(
    search_phrase: str,
    class_id: int,
    resource_ids: Optional[list[int]] = None,
    chapter_ids: Optional[list[int]] = None,
    subchapter_ids: Optional[list[int]] = None,
) -> SearchKnowledgeResult:
    try:
        # Retrieve the resources for the class
        class_resource_ids = await db.get_class_resources(class_id)

        # Retrieve the relevant content
        retrieved_content = await vector_search(
            query=search_phrase,
            n_results=tool_settings.search_knowledge_n_results,
            where={
                "chunk_type": [ChunkType.text],
                "resource_id": resource_ids,
            },
        )
        logger.debug(
            f"Retrieved {len(retrieved_content)} content chunks, this is the first: {retrieved_content[0]}"
        )

        chunk_ids = [chunk.id for chunk in retrieved_content]
        return {
            "content": _format_context(retrieved_content),
            "source_chunk_ids": chunk_ids,
        }
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
        context_parts.append(
            f'Cite as: {{{{TWIGA_CITATION:{{"chunk_id":{chunk.id}}}}}}}\n'
        )

    return str("\n".join(context_parts))
