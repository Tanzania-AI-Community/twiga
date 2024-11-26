import logging
from typing import List, Optional
from app.database.db import vector_search
from app.database.models import Chunk, Resource, User
from app.services.whatsapp_service import whatsapp_client
from app.utils.string_manager import strings, StringCategory
from app.database.enums import ChunkType

logger = logging.getLogger(__name__)


# Example function to make available to model
async def search_knowledge(
    search_phrase: str,
    user: User,
    resources: List[int],
    # subject: Subject = Subject.geography,
    # grade_level: GradeLevel = GradeLevel.os2,
):
    try:
        await whatsapp_client.send_message(
            user.wa_id, strings.get_string(StringCategory.TOOLS, "search_knowledge")
        )
        # Retrieve the relevant content
        retrieved_content = await vector_search(
            query=search_phrase,
            n_results=10,
            where={
                "content_type": [ChunkType.text],
                "resource_id": resources,
            },
        )

        logger.debug(
            f"Retrieved {len(retrieved_content)} content chunks, this is the first: {retrieved_content[0]}"
        )

        # Format the context and prompt
        return _format_context(retrieved_content)

    except Exception as e:
        logger.error(f"An error occurred when searching the knowledge base: {e}")
        return None


def _format_context(
    retrieved_content: List[Chunk],
    resources: Optional[List[Resource]] = None,
):
    # Formatting the context
    context_parts = []
    if resources:
        if len(resources) == 1:
            context_parts.append(
                f"### Context from the resource ({resources[0].name})\n"
            )
        else:
            resource_titles = ", ".join(
                [f"{resource.id}. {resource.name}" for resource in resources]
            )
            context_parts.append(
                f"### Context from the resources ({resource_titles})\n"
            )

    for chunk in retrieved_content:
        if chunk.top_level_section_title and chunk.top_level_section_index:
            heading = f"-{chunk.content_type} from chapter {chunk.top_level_section_index}. {chunk.top_level_section_title} in resource {chunk.resource_id}"
        elif chunk.top_level_section_title:
            heading = f"-{chunk.content_type} from section {chunk.top_level_section_title} in resource {chunk.resource_id}"
        else:
            heading = f"-{chunk.content_type} from resource {chunk.resource_id}"

        context_parts.append(heading)
        context_parts.append(f"{chunk.content}")

    return "\n".join(context_parts)
