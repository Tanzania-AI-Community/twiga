from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.database.enums import ChunkType, GradeLevel, SubjectClassStatus
from app.tools.registry import TOOLS_METADATA


@pytest.mark.asyncio
@patch("app.tools.tool_code.search_knowledge.main.vector_search", new_callable=AsyncMock)
@patch("app.tools.tool_code.search_knowledge.main.db.get_class_resources", new_callable=AsyncMock)
@patch(
    "app.tools.tool_code.search_knowledge.main.db.read_class_by_subject_id_grade_level_and_status",
    new_callable=AsyncMock,
)
@patch("app.tools.tool_code.search_knowledge.main.db.read_subject_by_name", new_callable=AsyncMock)
@patch("app.tools.tool_code.search_knowledge.main.db.read_classes", new_callable=AsyncMock)
async def test_search_knowledge_uses_subject_specific_class_when_available(
    mock_read_classes,
    mock_read_subject_by_name,
    mock_read_class_by_subject,
    mock_get_class_resources,
    mock_vector_search,
):
    from app.tools.tool_code.search_knowledge.main import search_knowledge

    mock_read_classes.return_value = [
        SimpleNamespace(
            grade_level=GradeLevel.os2,
            status=SubjectClassStatus.active,
        )
    ]
    mock_read_subject_by_name.return_value = SimpleNamespace(id=7)
    mock_read_class_by_subject.return_value = SimpleNamespace(id=42)
    mock_get_class_resources.return_value = [99]
    mock_vector_search.return_value = [
        SimpleNamespace(
            chunk_type=ChunkType.text,
            top_level_section_title="Atoms",
            resource_id=99,
            content="Matter is made of atoms.",
        )
    ]

    result = await search_knowledge(
        search_phrase="Explain atoms",
        class_id=5,
        subject="Chemistry",
    )

    mock_read_classes.assert_awaited_once_with([5])
    mock_read_subject_by_name.assert_awaited_once_with("chemistry")
    mock_read_class_by_subject.assert_awaited_once_with(
        subject_id=7,
        grade_level="os2",
        status="active",
    )
    mock_get_class_resources.assert_awaited_once_with(42)
    assert "Matter is made of atoms." in result


@pytest.mark.asyncio
@patch("app.tools.tool_code.search_knowledge.main.vector_search", new_callable=AsyncMock)
@patch("app.tools.tool_code.search_knowledge.main.db.get_class_resources", new_callable=AsyncMock)
@patch(
    "app.tools.tool_code.search_knowledge.main.db.read_class_by_subject_id_grade_level_and_status",
    new_callable=AsyncMock,
)
@patch("app.tools.tool_code.search_knowledge.main.db.read_subject_by_name", new_callable=AsyncMock)
@patch("app.tools.tool_code.search_knowledge.main.db.read_classes", new_callable=AsyncMock)
async def test_search_knowledge_falls_back_to_given_class_without_subject(
    mock_read_classes,
    mock_read_subject_by_name,
    mock_read_class_by_subject,
    mock_get_class_resources,
    mock_vector_search,
):
    from app.tools.tool_code.search_knowledge.main import search_knowledge

    mock_get_class_resources.return_value = [5]
    mock_vector_search.return_value = [
        SimpleNamespace(
            chunk_type=ChunkType.text,
            top_level_section_title=None,
            resource_id=5,
            content="Fallback content",
        )
    ]

    result = await search_knowledge(search_phrase="Explain weather", class_id=3)

    mock_read_classes.assert_not_called()
    mock_read_subject_by_name.assert_not_called()
    mock_read_class_by_subject.assert_not_called()
    mock_get_class_resources.assert_awaited_once_with(3)
    assert "Fallback content" in result


def test_search_knowledge_metadata_accepts_optional_subject():
    search_tool = next(
        tool for tool in TOOLS_METADATA if tool["function"]["name"] == "search_knowledge"
    )

    parameters = search_tool["function"]["parameters"]

    assert "subject" in parameters["properties"]
    assert parameters["required"] == ["search_phrase", "class_id"]
