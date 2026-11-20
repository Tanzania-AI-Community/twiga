import asyncio
import logging
import time
from functools import lru_cache
from typing import Optional, TypedDict

import app.database.db as db
from app.config import embedding_settings, llm_settings, tool_settings
from app.database.db import vector_search
from app.database.enums import ChunkType
from app.database.models import Chunk, Resource
from app.utils.reranker import Reranker, get_reranker

logger = logging.getLogger(__name__)


class SearchKnowledgeResult(TypedDict):
    content: str
    source_chunk_ids: list[int]


async def search_knowledge(
    search_phrase: str,
    class_id: int,
) -> SearchKnowledgeResult:
    try:
        # Retrieve the resources for the class
        resource_ids = await db.get_class_resources(class_id)
        assert resource_ids

        # Retrieve the relevant content, with a larger pool when reranking
        n_results = tool_settings.search_knowledge_n_results
        rerank = tool_settings.search_knowledge_rerank_enabled
        retrieved_content = await vector_search(
            query=search_phrase,
            n_results=(
                max(tool_settings.search_knowledge_rerank_candidate_pool, n_results)
                if rerank
                else n_results
            ),
            where={
                "chunk_type": [ChunkType.text],
                "resource_id": resource_ids,
            },
        )
        if rerank:
            retrieved_content = await _rerank(
                search_phrase, retrieved_content, n_results
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


@lru_cache(maxsize=1)
def _get_reranker() -> Reranker:
    return get_reranker(
        provider=tool_settings.search_knowledge_rerank_provider,
        model=tool_settings.search_knowledge_rerank_model,
        timeout_seconds=tool_settings.search_knowledge_rerank_timeout,
        api_key=(
            llm_settings.api_key.get_secret_value() if llm_settings.api_key else None
        ),
        project=embedding_settings.google_cloud_project,
    )


async def _rerank(query: str, chunks: list[Chunk], n_results: int) -> list[Chunk]:
    """Reorder chunks by reranker relevance; fall back to vector order on failure."""
    if len(chunks) <= 1:
        return chunks[:n_results]
    start = time.perf_counter()
    try:
        order = await asyncio.wait_for(
            _get_reranker().rank(query, [chunk.content for chunk in chunks]),
            timeout=tool_settings.search_knowledge_rerank_timeout,
        )
        reranked = [chunks[i] for i in dict.fromkeys(order) if 0 <= i < len(chunks)]
        if not reranked:
            raise ValueError("Reranker returned no valid indices.")
        logger.info(
            f"Reranked {len(chunks)} chunks in {time.perf_counter() - start:.2f}s"
        )
        return reranked[:n_results]
    except Exception as e:
        logger.warning(
            f"Reranking failed after {time.perf_counter() - start:.2f}s, "
            f"using vector order: {e!r}"
        )
        return chunks[:n_results]


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
