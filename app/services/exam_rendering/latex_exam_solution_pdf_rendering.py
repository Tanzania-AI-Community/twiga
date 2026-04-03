from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.services.exam_rendering.latex_exam_pdf_rendering import (
    build_document_end,
    build_document_start,
    build_header,
    build_instructions,
    build_section_a,
    build_section_b,
    build_section_c,
    normalize_inline_text,
)
from app.services.latex_image_service import build_latex_document_pdf_at_path

logger = logging.getLogger(__name__)


def build_solution_header(meta: dict[str, Any]) -> str:
    """Build the exam solution header block from metadata.

    Args:
        meta: Metadata dictionary containing country, office, exam title, subject,
            duration, and year fields.
    Returns:
        A LaTeX header block for the solution PDF, which can be styled differently from the exam header.
    """
    header_string = build_header(meta)

    # change header to solution header
    exam_title = normalize_inline_text(meta.get("exam_title", ""))
    if exam_title:
        solution_exam_title = exam_title + " - MARKING SCHEME / SOLUTION KEY"
        header_string = header_string.replace(exam_title, solution_exam_title)

    return header_string


def build_solution_section_a(section_a_data: dict[str, Any]) -> str:
    """Build the LaTeX for Section A of the solution PDF, which includes the correct answers and solution explanations.

    Args:
        section_a_data: The JSON data for Section A, including questions, options, correct answers, and solutions.
    Returns:
        A LaTeX string for Section A of the solution PDF, which can include additional formatting to highlight correct answers and solutions.
    """
    section_a_string, section_a_lines = build_section_a(section_a_data)
    if not section_a_string:
        return ""

    for line in section_a_lines:
        logger.debug(f"Section A line: {line}")

    # add solutions for multiple choice questions

    # add solutions for matching questions

    return section_a_string


def build_solution_section_b(section_b_data: dict[str, Any]) -> str:
    """Build the LaTeX for Section B of the solution PDF, which includes the correct answers and solution explanations.

    Args:
        section_b_data: The JSON data for Section B, including questions, options, correct answers, and solutions.
    Returns:
        A LaTeX string for Section B of the solution PDF, which can include additional formatting to highlight correct answers and solutions.
    """
    # NOTE: need to implement
    section_b_string, section_b_lines = build_section_b(section_b_data)
    if not section_b_string:
        return ""

    for line in section_b_lines:
        logger.debug(f"Section B line: {line}")

    return section_b_string


def build_solution_section_c(section_c_data: dict[str, Any]) -> str:
    """Build the LaTeX for Section C of the solution PDF, which includes the correct answers and solution explanations.

    Args:
        section_c_data: The JSON data for Section C, including questions, options, correct answers, and solutions.
    Returns:
        A LaTeX string for Section C of the solution PDF, which can include additional formatting to highlight correct answers and solutions.
    """
    # NOTE: need to implement
    section_c_string, section_c_lines = build_section_c(section_c_data)
    if not section_c_string:
        return ""

    for line in section_c_lines:
        logger.debug(f"Section C line: {line}")

    return section_c_string


def build_exam_solution_document(data: dict[str, Any]) -> str:
    """Assemble the full LaTeX solution document from parsed JSON exam data.

    Args:
        data: Full exam JSON dictionary.

    Returns:
        A complete LaTeX document string ready to write to disk.
    """
    parts = [
        build_document_start(),
        build_solution_header(data.get("meta", {})),
        build_instructions(data.get("instructions", [])),
        build_solution_section_a(data.get("section_A", {})),
        build_solution_section_b(data.get("section_B", {})),
        build_solution_section_c(data.get("section_C", {})),
        build_document_end(),
    ]
    return "\n\n".join(part for part in parts if part.strip()) + "\n"


######## Interface function ###########
def build_latex_exam_solution_pdf(exam: dict[str, Any], out_path: str | Path) -> None:
    """
    Build a LaTeX exam solution PDF from JSON exam data.

    Args:
        exam: The exam data in JSON format.
        out_path: The path where the generated PDF will be saved.
    """
    try:
        latex_doc = build_exam_solution_document(exam)
    except Exception as e:
        logger.error(f"Error building LaTeX solution document string: {e}")
        raise RuntimeError("Failed to build LaTeX solution document string") from e

    logger.debug(f"Generated LaTeX solution document string:\n{latex_doc}")

    try:
        build_latex_document_pdf_at_path(
            latex_document=latex_doc,
            out_path=out_path,
        )
    except Exception as e:
        logger.error(f"Error building LaTeX exam solution PDF: {e}")
        raise RuntimeError(
            "Failed to build LaTeX exam solution PDF from document string"
        )
