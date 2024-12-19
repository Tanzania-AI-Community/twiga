import logging
from typing import List, Optional

from app.utils.llm_utils import async_llm_request
from app.utils.prompt_manager import prompt_manager
from app.database.db import vector_search
from app.database.models import Chunk, Resource, User
from app.config import llm_settings
from app.services.whatsapp_service import whatsapp_client
from app.utils.string_manager import strings, StringCategory
from app.database.enums import ChunkType

logger = logging.getLogger(__name__)


async def generate_exercise(
    query: str,
    user: User,
    resources: List[int],
) -> str:

    # TODO: Redesign this function to search on only the relevant resources
    try:
        # TODO: Technically only send this once in case multiple tools called at once, but for now it's fine
        await whatsapp_client.send_message(
            user.wa_id, strings.get_string(StringCategory.TOOLS, "exercise_generator")
        )

        # Retrieve the relevant content and exercises
        retrieved_content = await vector_search(
            query=query,
            n_results=7,
            where={
                "chunk_type": [ChunkType.text],
                "resource_id": resources,
            },
        )
        retrieved_exercises = await vector_search(
            query=query,
            n_results=3,
            where={
                "chunk_type": [ChunkType.exercise],
                "resource_id": resources,
            },
        )

        logger.debug(
            f"Retrieved {len(retrieved_content)} content chunks, this is the first: {retrieved_content[0]}"
        )
        logger.debug(
            f"Retrieved {len(retrieved_content)} exercise chunks, this is the first: {retrieved_content[0]}"
        )

        # Format the context and prompt
        context = _format_context(retrieved_content, retrieved_exercises)
        system_prompt = prompt_manager.get_prompt("exercise_generator_system")

        user_prompt = prompt_manager.format_prompt(
            "exercise_generator_user", query=query, context_str=context
        )

        # Generate a question based on the context
        return await _generate(system_prompt, user_prompt)
    except Exception as e:
        logger.error(f"An error occurred when generating an exercise: {e}")
        return None


async def _generate(prompt: str, query: str, verbose: bool = False) -> str:
    try:
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": query},
        ]

        if verbose:
            print("--------------------------")
            print(f"System prompt: \n{prompt}")
            print("--------------------------")
            print(f"User prompt: \n{query}")

        res = await async_llm_request(
            model=llm_settings.exercise_generator_model,
            messages=messages,
            max_tokens=100,
        )

        return res.choices[0].message.content

    except Exception as e:
        logger.error(f"An error occurred when generating a response query: {e}")
        return None


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
