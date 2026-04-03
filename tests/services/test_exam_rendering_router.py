from pathlib import Path
from unittest.mock import Mock, patch

from app.services.exam_pdf_generation_service import (
    ExamRenderType,
    backend_for_subject,
    normalize_subject_for_routing,
    render_exam_pdf,
    render_exam_solution_pdf,
)


def test_normalize_subject_for_routing_handles_basic_variants() -> None:
    assert normalize_subject_for_routing(" MATHEMATICS ") == "mathematics"
    assert normalize_subject_for_routing("Chemistry") == "chemistry"
    assert normalize_subject_for_routing("PHYSICS") == "physics"
    assert normalize_subject_for_routing("Math") == "mathematics"


def test_backend_for_subject_defaults_to_latex() -> None:
    assert backend_for_subject("Mathematics") is ExamRenderType.LATEX
    assert backend_for_subject("chemistry") is ExamRenderType.LATEX
    assert backend_for_subject("geography") is ExamRenderType.LATEX


def test_backend_for_subject_raises_for_none_subject() -> None:
    try:
        backend_for_subject(None)
    except ValueError as exc:
        assert "Subject cannot be None" in str(exc)
    else:
        raise AssertionError("Expected ValueError for None subject")


def test_render_exam_pdf_uses_latex_backend_when_latex_succeeds(tmp_path: Path) -> None:
    out_path = tmp_path / "exam.pdf"
    exam = {"meta": {"subject": "Geography"}}
    with (
        patch(
            "app.services.exam_pdf_generation_service.build_latex_exam_pdf"
        ) as mock_render_latex,
        patch(
            "app.services.exam_pdf_generation_service.build_reportlab_exam_pdf"
        ) as mock_render_reportlab,
    ):
        render_exam_pdf(exam, out_path, subject="Geography")

    mock_render_latex.assert_called_once_with(exam, out_path)
    mock_render_reportlab.assert_not_called()


def test_render_exam_pdf_falls_back_to_reportlab_when_latex_fails(
    tmp_path: Path,
) -> None:
    out_path = tmp_path / "exam.pdf"
    exam = {"meta": {"subject": "Mathematics"}}
    logger = Mock()

    def _fake_reportlab_renderer(_: dict, output_path: Path) -> None:
        output_path.write_bytes(b"reportlab")

    with (
        patch(
            "app.services.exam_pdf_generation_service.build_latex_exam_pdf",
            side_effect=RuntimeError("compile failed"),
        ) as mock_render_latex,
        patch(
            "app.services.exam_pdf_generation_service.build_reportlab_exam_pdf",
            side_effect=_fake_reportlab_renderer,
        ) as mock_render_reportlab,
        patch("app.services.exam_pdf_generation_service.logger", logger),
    ):
        render_exam_pdf(exam, out_path, subject="Mathematics")

    assert out_path.read_bytes() == b"reportlab"
    mock_render_latex.assert_called_once()
    mock_render_reportlab.assert_called_once()
    logger.warning.assert_called_once()
    message = logger.warning.call_args[0][0]
    assert "falling back to ReportLab" in message


def test_render_exam_solution_pdf_uses_reportlab_solution_backend(
    tmp_path: Path,
) -> None:
    out_path = tmp_path / "solution.pdf"
    exam = {"meta": {"subject": "Mathematics"}}

    with patch(
        "app.services.exam_pdf_generation_service.build_reportlab_solution_pdf"
    ) as mock_render_reportlab_solution:
        render_exam_solution_pdf(exam, out_path, subject="Mathematics")

    mock_render_reportlab_solution.assert_called_once_with(exam, out_path)
