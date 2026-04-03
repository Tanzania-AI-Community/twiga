import logging
from enum import Enum
from pathlib import Path
from typing import Any

from app.services.exam_rendering.latex_exam_pdf_rendering import (
    build_latex_exam_pdf,
)
from app.services.exam_rendering.reportlab_rendering import (
    build_reportlab_exam_pdf,
    build_reportlab_solution_pdf,
)

logger = logging.getLogger(__name__)

LATEX_SUBJECTS: set[str] = {"mathematics", "physics"}  # "chemistry"


class ExamRenderType(str, Enum):
    REPORTLAB = "reportlab"
    LATEX = "latex"


def normalize_subject_for_routing(subject: str | None) -> None | str:
    if not isinstance(subject, str):
        return None
    normalized = subject.strip().lower().replace("-", "_")
    normalized = " ".join(normalized.split())
    normalized = normalized.replace(" ", "_")
    aliases: dict[str, str] = {
        "math": "mathematics",
        "maths": "mathematics",
        "chem": "chemistry",
        "phy": "physics",
    }
    return aliases.get(normalized, normalized)


def backend_for_subject(subject: str | None) -> ExamRenderType:
    normalized_subject = normalize_subject_for_routing(subject)
    if normalized_subject is None:
        raise ValueError("Subject cannot be None for exam rendering backend selection.")

    # if normalized_subject in LATEX_SUBJECTS:
    #     return ExamRenderType.LATEX
    # return ExamRenderType.REPORTLAB

    """
    NOTE:
    For now, we will default to LaTex for all subjects
    and have ReportLab as a fallback in case of errors,
    since the LaTeX rendering is generally better and we
    want to prioritize it.
    """
    return ExamRenderType.LATEX


def render_exam_pdf(
    exam_json: dict[str, Any], output_path: str | Path, subject: str
) -> None:
    selected_backend = backend_for_subject(subject)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if selected_backend == ExamRenderType.LATEX:
        try:
            build_latex_exam_pdf(exam_json, output_path)
            return
        except Exception as exc:
            logger.warning(
                "LaTeX backend failed; falling back to ReportLab. error=%s",
                str(exc),
            )

    build_reportlab_exam_pdf(exam_json, output_path)
    return


def render_exam_solution_pdf(
    exam_json: dict[str, Any], output_path: str | Path, subject: str
) -> None:
    selected_backend = backend_for_subject(subject)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if selected_backend == ExamRenderType.LATEX:
        # try:
        #     build_latex_solution_pdf(exam_json, output_path)
        #     return
        # except Exception as exc:
        #     logger.warning(
        #         "LaTeX backend failed; falling back to ReportLab. error=%s",
        #         str(exc),
        #     )
        logger.debug(
            "LaTeX solution PDF rendering is not implemented; falling back to ReportLab."
        )

    build_reportlab_solution_pdf(exam_json, output_path)
    return
