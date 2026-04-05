import json
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import selectinload

import app.database.db as db
from app.database.models import Chunk

CITATION_MARKER_RE = re.compile(
    r"\{\{?TWIGA_CITATION:\s*(\{.*?\})\}\}?",
    re.DOTALL,
)

FAILED_SOURCE_TEXT = "Failed to retrieve source information"


@dataclass
class CitationRenderResult:
    marker_found: bool
    rendered_content: str
    ordered_chunk_ids: list[int] = field(default_factory=list)
    valid_marker_count: int = 0
    invalid_marker_count: int = 0


@dataclass
class SourceInfo:
    chunk_id: int | None
    resource_id: int | None
    citation_text: str
    valid_source: bool


class CitationService:
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    async def render_citations(self, content: str | None) -> CitationRenderResult:
        if content is None:
            self.logger.warning(
                "Skipping citation marker parsing because content is None."
            )
            return CitationRenderResult(
                marker_found=False,
                rendered_content="",
            )

        matches = list(CITATION_MARKER_RE.finditer(content))
        if not matches:
            return CitationRenderResult(
                marker_found=False,
                rendered_content=content,
            )

        id_to_source_info: dict[int, SourceInfo] = {}
        id_to_marker_texts: dict[int, set[str]] = {}
        valid_marker_count = 0
        invalid_marker_count = 0

        for match in matches:
            marker_text = match.group(0)
            chunk_id = self._get_chunk_id_from_marker(match)

            if chunk_id is None:
                self.logger.warning(
                    f"Invalid marker payload, unable to extract chunk_id: {match.group(1)}"
                )
                content = self._handle_invalid_marker(content, marker_text)
                invalid_marker_count += 1
                continue

            if chunk_id not in id_to_source_info:
                source_info = await self._get_source_info_for_marker(chunk_id=chunk_id)
                self.logger.debug(
                    f"Source info: {source_info} for marker: {marker_text}"
                )
                id_to_source_info[chunk_id] = source_info

            # Keep the exact marker text for each chunk so replacements/removals use
            # what was actually generated in content.
            id_to_marker_texts.setdefault(chunk_id, set()).add(marker_text)

            source_info = id_to_source_info[chunk_id]
            if source_info.valid_source:
                valid_marker_count += 1
            else:
                invalid_marker_count += 1

        # since dict keys are orders in python 3.7+, the sources will be ordered by first appearance in content
        content_with_sources = self._add_citations_to_content(
            content=content,
            id_to_source_info=id_to_source_info,
            id_to_marker_texts=id_to_marker_texts,
        )

        ordered_chunk_ids = [
            chunk_id
            for chunk_id, source_info in id_to_source_info.items()
            if source_info.valid_source and chunk_id in id_to_marker_texts
        ]

        return CitationRenderResult(
            marker_found=True,
            rendered_content=content_with_sources,
            ordered_chunk_ids=ordered_chunk_ids,
            valid_marker_count=valid_marker_count,
            invalid_marker_count=invalid_marker_count,
        )

    async def _get_source_info_for_marker(self, chunk_id: int) -> SourceInfo:
        """
        Given a chunk ID, retrieve the source information.
        """
        async with db.get_session() as session:
            statement = (
                db.select(Chunk)
                .options(selectinload(Chunk.resource_))
                .where(Chunk.id == chunk_id)
            )
            result = await session.execute(statement)
            chunk = result.scalar_one_or_none()

        if chunk is None:
            self.logger.warning(f"CitationService: Chunk not found for ID: {chunk_id}")
            return SourceInfo(
                chunk_id=chunk_id,
                resource_id=None,
                citation_text=FAILED_SOURCE_TEXT,
                valid_source=False,
            )

        if chunk.resource_id is None:
            self.logger.warning(
                f"CitationService: Chunk found but has no associated resource for ID: {chunk_id}"
            )
            return SourceInfo(
                chunk_id=chunk.id,
                resource_id=None,
                citation_text=FAILED_SOURCE_TEXT,
                valid_source=False,
            )

        resource_name = chunk.resource_.name if chunk.resource_ else None
        page_number = chunk.page_number
        section_title = chunk.top_level_section_title

        if resource_name:
            if page_number is not None:
                citation_text = f"{resource_name}, page {page_number}"
            elif section_title:
                citation_text = f"{resource_name}, {section_title}"
            else:
                citation_text = resource_name
        else:
            citation_text = FAILED_SOURCE_TEXT

        return SourceInfo(
            chunk_id=chunk.id,
            resource_id=chunk.resource_id,
            citation_text=citation_text,
            valid_source=True,
        )

    def _get_chunk_id_from_marker(self, match: re.Match[str]) -> int | None:
        try:
            payload = json.loads(match.group(1))
            chunk_id = payload.get("chunk_id")
            if isinstance(chunk_id, int) and chunk_id > 0:
                return chunk_id
            else:
                return None
        except json.JSONDecodeError:
            return None

    def _add_citations_to_content(
        self,
        content: str,
        id_to_source_info: dict[int, SourceInfo],
        id_to_marker_texts: dict[int, set[str]],
    ) -> str:
        source_footer_lines: list[str] = ["Sources:"]
        citation_index = 1

        for chunk_id, source_info in id_to_source_info.items():
            if not source_info.valid_source:
                self.logger.warning(
                    f"Invalid source for chunk_id {chunk_id}, skipping citation. Source info: {source_info}"
                )
                marker_texts = id_to_marker_texts.get(chunk_id, set())
                content = self._handle_invalid_source(content, marker_texts)
                continue

            for marker_text in id_to_marker_texts.get(chunk_id, set()):
                content = content.replace(marker_text, f" [{citation_index}]")

            source_footer_lines.append(
                f"[{citation_index}] {source_info.citation_text}"
            )
            citation_index += 1

        content = self._normalize_citation_spacing(content)
        if citation_index == 1:
            return content

        return content + "\n\n" + "\n".join(source_footer_lines)

    @staticmethod
    def _handle_invalid_marker(content: str, marker_text: str) -> str:
        return content.replace(marker_text, "")

    @staticmethod
    def _handle_invalid_source(content: str, marker_texts: set[str]) -> str:
        for marker_text in marker_texts:
            content = content.replace(marker_text, "")
        return content

    @staticmethod
    def _normalize_citation_spacing(content: str) -> str:
        content = re.sub(r"\s+\[([0-9]+)\]\s*([,.;:!?])", r" [\1]\2", content)
        content = re.sub(r"[ \t]{2,}", " ", content)
        return content.strip()


citation_service = CitationService()
