import logging
from typing import List, Optional
from app.database.db import vector_search
from app.database.models import Chunk, Resource
from app.database.enums import ChunkType
import app.database.db as db

logger = logging.getLogger(__name__)


async def search_knowledge(
    search_phrase: str,
    class_id: int,
) -> str:
    try:
        # Retrieve the resources for the class
        resource_ids = await db.get_class_resources(class_id)
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
    retrieved_content: List[Chunk],
    resources: Optional[List[Resource]] = None,
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
