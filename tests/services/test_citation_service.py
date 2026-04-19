from unittest.mock import AsyncMock, patch

import pytest

from app.services.citation_service import (
    FAILED_SOURCE_TEXT,
    SourceInfo,
    citation_service,
)


@pytest.mark.asyncio
async def test_render_citations_rewrites_markers_to_inline_and_appends_sources() -> (
    None
):
    content = (
        "Plants make food using sunlight"
        '{{TWIGA_CITATION:{"chunk_id":101}}}, and chlorophyll absorbs light'
        '{{TWIGA_CITATION:{"chunk_id":102}}}.'
    )

    with patch.object(
        citation_service,
        "_get_source_info_for_markers",
        AsyncMock(
            return_value={
                101: SourceInfo(
                    chunk_id=101,
                    resource_id=1,
                    citation_text="Book, page 1",
                    valid_source=True,
                ),
                102: SourceInfo(
                    chunk_id=102,
                    resource_id=1,
                    citation_text="Book, page 2",
                    valid_source=True,
                ),
            }
        ),
    ) as mock_batch_lookup:
        result = await citation_service.render_citations(content)

    mock_batch_lookup.assert_awaited_once_with(chunk_id_list=[101, 102])

    assert result.marker_found is True
    assert result.valid_reference_count == 2
    assert result.invalid_reference_count == 0
    assert result.ordered_chunk_ids == [101, 102]
    assert (
        result.rendered_content
        == "Plants make food using sunlight [1], and chlorophyll absorbs light [2].\n\n"
        "Sources:\n"
        "- [1] Book, page 1\n"
        "- [2] Book, page 2"
    )


@pytest.mark.asyncio
async def test_render_citations_deduplicates_repeated_chunk_markers() -> None:
    content = (
        "Evaporation turns liquid water into vapor"
        '{{TWIGA_CITATION:{"chunk_id":77}}} and this process needs heat'
        '{{TWIGA_CITATION:{"chunk_id":77}}}.'
    )

    with patch.object(
        citation_service,
        "_get_source_info_for_markers",
        AsyncMock(
            return_value={
                77: SourceInfo(
                    chunk_id=77,
                    resource_id=1,
                    citation_text="Book, page 1",
                    valid_source=True,
                )
            }
        ),
    ) as mock_batch_lookup:
        result = await citation_service.render_citations(content)

    mock_batch_lookup.assert_awaited_once_with(chunk_id_list=[77])

    assert result.marker_found is True
    assert result.valid_reference_count == 2
    assert result.invalid_reference_count == 0
    assert result.ordered_chunk_ids == [77]
    assert (
        result.rendered_content
        == "Evaporation turns liquid water into vapor [1] and this process needs heat [1].\n\n"
        "Sources:\n"
        "- [1] Book, page 1"
    )


@pytest.mark.asyncio
async def test_render_citations_removes_invalid_marker_payloads_fail_soft() -> None:
    content = (
        "Photosynthesis happens in green leaves"
        '{{TWIGA_CITATION:{"chunk_id":"not-an-int"}}}.'
    )

    result = await citation_service.render_citations(content)

    assert result.marker_found is True
    assert result.valid_reference_count == 0
    assert result.invalid_reference_count == 1
    assert result.ordered_chunk_ids == []
    assert result.rendered_content == "Photosynthesis happens in green leaves."


@pytest.mark.asyncio
async def test_render_citations_removes_marker_when_source_is_invalid() -> None:
    content = 'Fact from textbook{{TWIGA_CITATION:{"chunk_id":88}}}.'

    with patch.object(
        citation_service,
        "_get_source_info_for_markers",
        AsyncMock(
            return_value={
                88: SourceInfo(
                    chunk_id=88,
                    resource_id=None,
                    citation_text=None,
                    valid_source=False,
                )
            }
        ),
    ) as mock_batch_lookup:
        result = await citation_service.render_citations(content)

    mock_batch_lookup.assert_awaited_once_with(chunk_id_list=[88])

    assert result.marker_found is True
    assert result.valid_reference_count == 0
    assert result.invalid_reference_count == 1
    assert result.ordered_chunk_ids == []
    assert result.rendered_content == "Fact from textbook."


@pytest.mark.asyncio
async def test_render_citations_uses_failed_source_text_when_label_is_missing() -> None:
    content = 'Fact from textbook{{TWIGA_CITATION:{"chunk_id":89}}}.'

    with patch.object(
        citation_service,
        "_get_source_info_for_markers",
        AsyncMock(
            return_value={
                89: SourceInfo(
                    chunk_id=89,
                    resource_id=7,
                    citation_text=FAILED_SOURCE_TEXT,
                    valid_source=True,
                )
            }
        ),
    ) as mock_batch_lookup:
        result = await citation_service.render_citations(content)

    mock_batch_lookup.assert_awaited_once_with(chunk_id_list=[89])

    assert result.marker_found is True
    assert result.valid_reference_count == 1
    assert result.invalid_reference_count == 0
    assert result.ordered_chunk_ids == [89]
    assert result.rendered_content == (
        "Fact from textbook [1].\n\n" "Sources:\n" f"- [1] {FAILED_SOURCE_TEXT}"
    )


@pytest.mark.asyncio
async def test_render_citations_returns_original_content_when_no_markers() -> None:
    content = "This answer has no citations."

    result = await citation_service.render_citations(content)

    assert result.marker_found is False
    assert result.valid_reference_count == 0
    assert result.invalid_reference_count == 0
    assert result.ordered_chunk_ids == []
    assert result.rendered_content == content
