import logging
from typing import List, Optional

from app.database import db
from app.utils.llm_utils import async_llm_request
from app.utils.prompt_manager import prompt_manager
from app.database.db import vector_search
from app.database.models import Chunk, Resource
from app.config import llm_settings
from app.database.enums import ChunkType

logger = logging.getLogger(__name__)


async def generate_exercise(
    query: str,
    class_id: int,
    subject: str,
) -> str:
    try:
        class_id = int(class_id)
        # Retrieve the resources for the class
        resource_ids = await db.get_class_resources(class_id)
        assert resource_ids

        # Retrieve the relevant content and exercises
        retrieved_content = await vector_search(
            query=query,
            n_results=7,
            where={
                "chunk_type": [ChunkType.text],
                "resource_id": resource_ids,
            },
        )
        retrieved_exercises = await vector_search(
            query=query,
            n_results=3,
            where={
                "chunk_type": [ChunkType.exercise],
                "resource_id": resource_ids,
            },
        )

        logger.debug(
            f"Retrieved {len(retrieved_content)} content chunks, this is the first: {retrieved_content[0]}"
        )
        logger.debug(
            f"Retrieved {len(retrieved_content)} exercise chunks, this is the first: {retrieved_content[0]}"
        )
    except Exception as e:
        logger.error(f"An error occurred when generating an exercise: {e}")
        raise Exception(
            "Failed to find content from the textbooks to generate this exercise. Skipping."
        )

    try:
        # Format the context and prompt
        context = _format_context(retrieved_content, retrieved_exercises)
        system_prompt = prompt_manager.format_prompt(
            "exercise_generator_system", class_info=subject
        )
        user_prompt = prompt_manager.format_prompt(
            "exercise_generator_user", query=query, context_str=context
        )

        # Convert to LangChain BaseMessage objects
        from langchain_core.messages import SystemMessage, HumanMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = await async_llm_request(
            messages=messages,
            model=llm_settings.exercise_generator_model,
            max_tokens=100,
        )
        assert response.content

        # Convert content to string if it's not already
        content = response.content
        if isinstance(content, list):
            # Handle list content by joining or extracting text
            content_str = ""
            for item in content:
                if isinstance(item, str):
                    content_str += item
                elif isinstance(item, dict) and "text" in item:
                    content_str += item["text"]
            return content_str
        elif isinstance(content, str):
            return content
        else:
            return str(content)
    except Exception as e:
        logger.error(f"An error occurred when generating an exercise: {e}")
        raise Exception("An error occurred when generating this exercise. Skipping.")


def _format_context(
    retrieved_content: List[Chunk],
    retrieved_exercise: List[Chunk],
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
            # TODO: Make this neater another time
            resource_titles = ", ".join(
                [f"{resource.id}. {resource.name}" for resource in resources]
            )
            context_parts.append(
                f"### Context from the resources ({resource_titles})\n"
            )

    for chunk in retrieved_content + retrieved_exercise:
        # TODO: Make this neater another time
        if chunk.top_level_section_title and chunk.top_level_section_index:
            heading = f"-{chunk.chunk_type} from chapter {chunk.top_level_section_index}. {chunk.top_level_section_title} in resource {chunk.resource_id}"
        elif chunk.top_level_section_title:
            heading = f"-{chunk.chunk_type} from section {chunk.top_level_section_title} in resource {chunk.resource_id}"
        else:
            heading = f"-{chunk.chunk_type} from resource {chunk.resource_id}"

        context_parts.append(heading)
        context_parts.append(f"{chunk.content}")

    return "\n".join(context_parts)
