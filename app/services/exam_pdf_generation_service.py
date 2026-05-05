import logging
from pathlib import Path
from typing import Any

from app.services.exam_rendering.latex_exam_pdf_rendering import (
    build_latex_exam_pdf,
)
from app.services.exam_rendering.latex_exam_solution_pdf_rendering import (
    build_latex_exam_solution_pdf,
)
from app.services.exam_rendering.reportlab_rendering import (
    build_reportlab_exam_pdf,
    build_reportlab_solution_pdf,
)

logger = logging.getLogger(__name__)


def render_exam_pdf(
    exam_json: dict[str, Any],
    output_path: str | Path,
) -> None:
    """
    Render an exam JSON payload to PDF.

    Tries the LaTeX renderer first and falls back to ReportLab if LaTeX rendering fails.

    Args:
        exam_json: The exam payload to render.
        output_path: Destination file path for the generated PDF.
    """
    try:
        build_latex_exam_pdf(exam_json, output_path)
        return
    except Exception as exc:
        logger.warning(
            f"LaTeX backend failed; falling back to ReportLab. error={str(exc)}",
        )

    build_reportlab_exam_pdf(exam_json, output_path)
    return


def render_exam_solution_pdf(
    exam_json: dict[str, Any], output_path: str | Path
) -> None:
    """
    Render an exam solution JSON payload to PDF.

    Tries the LaTeX renderer first and falls back to ReportLab if LaTeX rendering fails.

    Args:
        exam_json: The exam solution payload to render.
        output_path: Destination file path for the generated PDF.
    """
    try:
        build_latex_exam_solution_pdf(exam_json, output_path)
        return
    except Exception as exc:
        logger.warning(
            f"LaTeX backend failed; falling back to ReportLab. error={str(exc)}",
        )

    build_reportlab_solution_pdf(exam_json, output_path)
    return
