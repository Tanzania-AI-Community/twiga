from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.exam_delivery_service import ExamDeliveryService


def test_parse_delivery_marker_returns_valid_exam_id_and_cleaned_text() -> None:
    service = ExamDeliveryService()
    content = (
        "Your exam is ready.\n"
        '{{TWIGA_EXAM_DELIVERY:{"exam_id":"b1740ac9-bfea-415f-8b3a-c7f06ee8c353"}}}'
    )

    marker = service.parse_delivery_marker(content)

    assert marker.marker_found is True
    assert marker.marker_valid is True
    assert marker.exam_id == "b1740ac9-bfea-415f-8b3a-c7f06ee8c353"
    assert marker.cleaned_content == "Your exam is ready."


def test_parse_delivery_marker_single_brace_variant_is_supported() -> None:
    service = ExamDeliveryService()
    content = (
        "Your exam is ready.\n"
        '{TWIGA_EXAM_DELIVERY:{"exam_id":"b1740ac9-bfea-415f-8b3a-c7f06ee8c353"}}'
    )

    marker = service.parse_delivery_marker(content)

    assert marker.marker_found is True
    assert marker.marker_valid is True
    assert marker.exam_id == "b1740ac9-bfea-415f-8b3a-c7f06ee8c353"
    assert marker.cleaned_content == "Your exam is ready."


def test_parse_delivery_marker_invalid_payload_removes_marker_and_marks_invalid() -> (
    None
):
    service = ExamDeliveryService()
    content = "Your exam is ready.\n" '{{TWIGA_EXAM_DELIVERY:{"exam_id":"not-a-uuid"}}}'

    marker = service.parse_delivery_marker(content)

    assert marker.marker_found is True
    assert marker.marker_valid is False
    assert marker.exam_id is None
    assert marker.cleaned_content == "Your exam is ready."


@pytest.mark.asyncio
async def test_get_exam_delivery_details_uses_cache_and_returns_metadata(
    tmp_path: Path,
) -> None:
    service = ExamDeliveryService()
    exam_id = "b1740ac9-bfea-415f-8b3a-c7f06ee8c353"
    exam_pdf_path = tmp_path / f"exam_{exam_id}.pdf"
    solution_pdf_path = tmp_path / f"exam_{exam_id}_solution.pdf"
    exam_pdf_path.write_bytes(b"pdf")
    solution_pdf_path.write_bytes(b"pdf")
    exam_record = SimpleNamespace(
        subject="Geography",
        topics=["Climate", "Weather"],
        exam_json={
            "meta": {"subject": "Geography"},
            "generation_trace": {"topics": ["Climate", "Weather"]},
        },
    )

    with (
        patch(
            "app.services.exam_delivery_service.paths.EXAM_PDF_OUTPUT_DIR",
            tmp_path,
        ),
        patch(
            "app.services.exam_delivery_service.db.get_exam",
            AsyncMock(return_value=exam_record),
        ) as mock_get_exam,
    ):
        result = await service.get_exam_delivery_details(exam_id)

    assert result.exam_pdf_ready is True
    assert result.solution_pdf_ready is True
    assert result.subject == "Geography"
    assert result.topics == ["Climate", "Weather"]
    assert result.errors == []
    mock_get_exam.assert_awaited_once_with(exam_id)


@pytest.mark.asyncio
async def test_get_exam_delivery_details_renders_missing_pdfs_from_db(
    tmp_path: Path,
) -> None:
    service = ExamDeliveryService()
    exam_id = "b1740ac9-bfea-415f-8b3a-c7f06ee8c353"
    exam_record = SimpleNamespace(
        subject="Chemistry",
        topics=["Atomic Structure"],
        exam_json={"meta": {"exam_title": "Exam"}},
    )

    def _render_exam(
        exam_json: dict,
        output_path: Path,
        subject: str | None,
    ) -> None:
        assert exam_json == {"meta": {"exam_title": "Exam"}}
        assert subject == "Chemistry"
        output_path.write_bytes(b"pdf")

    def _render_solution(
        exam_json: dict,
        output_path: Path,
        subject: str | None,
    ) -> None:
        assert exam_json == {"meta": {"exam_title": "Exam"}}
        assert subject == "Chemistry"
        output_path.write_bytes(b"pdf")

    with (
        patch(
            "app.services.exam_delivery_service.paths.EXAM_PDF_OUTPUT_DIR",
            tmp_path,
        ),
        patch(
            "app.services.exam_delivery_service.db.get_exam",
            AsyncMock(return_value=exam_record),
        ) as mock_get_exam,
        patch(
            "app.services.exam_delivery_service.render_exam_pdf",
            side_effect=_render_exam,
        ) as mock_render_exam,
        patch(
            "app.services.exam_delivery_service.render_exam_solution_pdf",
            side_effect=_render_solution,
        ) as mock_render_solution,
    ):
        result = await service.get_exam_delivery_details(exam_id)

    assert result.exam_pdf_ready is True
    assert result.solution_pdf_ready is True
    assert result.errors == []
    mock_get_exam.assert_awaited_once_with(exam_id)
    mock_render_exam.assert_called_once()
    mock_render_solution.assert_called_once()


@pytest.mark.asyncio
async def test_get_exam_delivery_details_returns_error_when_exam_missing_in_db(
    tmp_path: Path,
) -> None:
    service = ExamDeliveryService()
    exam_id = "b1740ac9-bfea-415f-8b3a-c7f06ee8c353"

    with (
        patch(
            "app.services.exam_delivery_service.paths.EXAM_PDF_OUTPUT_DIR",
            tmp_path,
        ),
        patch(
            "app.services.exam_delivery_service.db.get_exam",
            AsyncMock(return_value=None),
        ),
    ):
        result = await service.get_exam_delivery_details(exam_id)

    assert result.exam_pdf_ready is False
    assert result.solution_pdf_ready is False
    assert any("not found" in error.lower() for error in result.errors)


def test_parse_delivery_marker_missing_exam_id_marks_invalid() -> None:
    service = ExamDeliveryService()
    content = 'Done {{TWIGA_EXAM_DELIVERY:{"send_solution":true}}}'

    marker = service.parse_delivery_marker(content)

    assert marker.marker_found is True
    assert marker.marker_valid is False
    assert marker.exam_id is None
    assert marker.cleaned_content == "Done"


def test_parse_delivery_marker_null_exam_id_marks_invalid() -> None:
    service = ExamDeliveryService()
    content = 'Done {{TWIGA_EXAM_DELIVERY:{"exam_id":null}}}'

    marker = service.parse_delivery_marker(content)

    assert marker.marker_found is True
    assert marker.marker_valid is False
    assert marker.exam_id is None
    assert marker.cleaned_content == "Done"
