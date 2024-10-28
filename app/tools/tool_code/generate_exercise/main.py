import logging
from typing import List, Literal

from app.database.vector_database import vector_client
from app.utils.llm_utils import async_groq_request, async_openai_request
from app.tools.tool_code.generate_exercise.models import RetrievedDocSchema
from app.tools.tool_code.generate_exercise.prompts import (
    PIPELINE_QUESTION_GENERATOR_PROMPT,
    PIPELINE_QUESTION_GENERATOR_USER_PROMPT,
)
from app.tools.tool_code.generate_exercise.modules import (
    chromadb_retriever,
    query_rewriter,
)

logger = logging.getLogger(__name__)


async def generate_exercise(user_query: str):
    # Rewrite the user query
    original_query = user_query
    rewritten_query = await query_rewriter(original_query, llm="llama3-8b-8192")

    verbose = False

    # Retrieve the relevant content and exercises
    retrieved_content: List[RetrievedDocSchema] = await chromadb_retriever(
        model_class=vector_client,
        retrieval_msg=rewritten_query,
        size=5,
        doc_type="Content",
        verbose=verbose,
    )
    retrieved_exercises: List[RetrievedDocSchema] = await chromadb_retriever(
        model_class=vector_client,
        retrieval_msg=rewritten_query,
        size=2,
        doc_type="Exercise",
        verbose=verbose,
    )

    # Format the context and prompt
    context = _format_context(retrieved_content, retrieved_exercises)
    system_prompt = PIPELINE_QUESTION_GENERATOR_PROMPT.format()
    user_prompt = PIPELINE_QUESTION_GENERATOR_USER_PROMPT.format(
        query=user_query, context_str=context
    )

    # Generate a question based on the context
    res = await _generate(system_prompt, user_prompt, model="llama3-70b-8192")
    return res


async def _generate(
    prompt: str,
    query: str,
    model: Literal["gpt-3.5-turbo-0125", "gpt-4-turbo-2024-04-09", "llama3-70b-8192"],
    verbose: bool = False,
) -> str:
    try:
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": query},
        ]

        if verbose:
            print(f"--------------------------")
            print(f"System prompt: \n{prompt}")
            print(f"--------------------------")
            print(f"User prompt: \n{query}")

        if model == "llama3-70b-8192":
            res = await async_groq_request(
                llm=model,
                verbose=False,
                messages=messages,
                max_tokens=100,
            )
        else:
            res = await async_openai_request(
                model=model,
                verbose=False,
                messages=messages,
                max_tokens=100,  # Adjust based on the expected length of the response
            )

        # Extract the enhanced query text from the response
        gen_query = res.choices[0].message.content

        return gen_query

    except Exception as e:
        logger.error(f"An error occurred when generating a response query: {e}")
        return None


def _format_context(
    retrieved_content: List[RetrievedDocSchema],
    retrieved_exercise: List[RetrievedDocSchema],
):
    # Format the context
    context_parts = []

    context_parts.append(
        f"### Context from the textbook ({retrieved_content[0].source.metadata.title})\n"
    )
    for index, doc in enumerate(retrieved_content):

        metadata = doc.source.metadata
        if metadata.chapter and metadata.subsection and metadata.subsubsection:
            heading = f"-Chunk number {index} from chapter {metadata.chapter}, subsection {metadata.subsection}, subsubsection {metadata.subsubsection}"
        elif metadata.chapter and metadata.subsection:
            heading = f"-Chunk number {index} from chapter {metadata.chapter}, subsection {metadata.subsection}"
        elif metadata.chapter:
            heading = f"-Chunk number {index} from chapter {metadata.chapter}"
        else:
            heading = f"-Chunk number {index}"

    context_parts.append(heading)
    context_parts.append(f"{doc.source.chunk}")

    context_parts.append(
        f"\n### Sample exercises from the textbook ({retrieved_content[0].source.metadata.title})\n"
    )
    for doc in retrieved_exercise:
        metadata = doc.source.metadata
        if metadata.chapter and metadata.subsection and metadata.subsubsection:
            heading = f"-Exercise of type {metadata.exercise_format} from chapter {metadata.chapter}, subsection {metadata.subsection}, subsubsection {metadata.subsubsection}"
        elif metadata.chapter and metadata.subsection:
            heading = f"-Exercise of type {metadata.exercise_format} from chapter {metadata.chapter}, subsection {metadata.subsection}"
        elif metadata.chapter:
            heading = f"-Exercise of type {metadata.exercise_format} from chapter {metadata.chapter}"
        else:
            heading = f"-Exercise of type {metadata.exercise_format}"

        context_parts.append(heading)
        context_parts.append(f"{doc.source.chunk}")

    return "\n".join(context_parts)
