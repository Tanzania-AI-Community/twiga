import logging
from typing import Optional

from app.database import db
from app.database.db import vector_search
from app.database.enums import ChunkType
from app.database.models import Chunk, Resource
from app.utils.llm_utils import async_llm_request
from app.utils.prompt_manager import prompt_manager

logger = logging.getLogger(__name__)


async def generate_exercise(
    query: str,
    class_id: int,
    subject: str,
) -> str:
    try:
        # Retrieve the resources for the class
        resource_ids = await db.get_class_resources(class_id)
        if not resource_ids:
            raise ValueError(f"No textbook resources found for class {class_id}")

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
            "Retrieved %s content chunks and %s exercise chunks",
            len(retrieved_content),
            len(retrieved_exercises),
        )
        if not retrieved_content:
            raise ValueError("No textbook content found for the exercise")
    except Exception as exc:
        logger.exception("Failed to retrieve textbook content for an exercise")
        raise Exception(
            "Failed to find content from the textbooks to generate this exercise. Skipping."
        ) from exc

    try:
        # Format the context and prompt
        context = _format_context(retrieved_content, retrieved_exercises)
        system_prompt_name = "exercise_generator_system"
        user_prompt_name = "exercise_generator_user"
        system_prompt = prompt_manager.format_prompt(
            system_prompt_name, class_info=subject
        )
        user_prompt = prompt_manager.format_prompt(
            user_prompt_name, query=query, context_str=context
        )

        # Convert to LangChain BaseMessage objects
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = await async_llm_request(
            messages=messages,
            max_tokens=2048,
            run_name="twiga_generate_exercise",
            metadata={
                "tool": "generate_exercise",
                "query": query,
                "class_id": str(class_id),
                "subject": subject,
                "content_chunks": (
                    len(retrieved_content) if "retrieved_content" in locals() else 0
                ),
                "exercise_chunks": (
                    len(retrieved_exercises) if "retrieved_exercises" in locals() else 0
                ),
                **prompt_manager.build_trace_metadata(
                    system_prompt_name=system_prompt_name,
                    user_prompt_name=user_prompt_name,
                ),
            },
        )
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
        elif isinstance(content, str):
            content_str = content
        else:
            content_str = str(content) if content is not None else ""

        if not content_str.strip():
            logger.error(
                "Exercise generation returned empty content: "
                "class_id=%s, response_metadata=%r, usage_metadata=%r",
                class_id,
                response.response_metadata,
                response.usage_metadata,
            )
            raise ValueError("Exercise generation returned no usable text")
        return content_str
    except Exception as exc:
        logger.exception("An error occurred when generating an exercise")
        raise Exception(
            "An error occurred when generating this exercise. Skipping."
        ) from exc


def _format_context(
    retrieved_content: list[Chunk],
    retrieved_exercise: list[Chunk],
    resources: Optional[list[Resource]] = None,
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
