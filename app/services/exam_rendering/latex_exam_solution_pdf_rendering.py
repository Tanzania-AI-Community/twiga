from __future__ import annotations

import logging
import re
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

MARKER_PATTERN = re.compile(r"^\s*%<TWIGA_SOLUTION:type=([^;>]+);id=([^>]+)>\s*$")


def normalize_marker_type(marker_type: str) -> str:
    """Normalize marker type tokens to uppercase alphanumeric+underscore form."""
    return re.sub(r"[^A-Z0-9_]", "_", str(marker_type).upper())


def normalize_marker_id(marker_id: str) -> str:
    """Normalize marker IDs to a stable safe character set used in LaTeX markers."""
    return re.sub(r"[^A-Za-z0-9_.:\-]", "_", str(marker_id))


def parse_solution_marker(line: str) -> tuple[str, str] | None:
    """Parse a marker line and return `(marker_type, marker_id)` or `None` if no marker is present."""
    match = MARKER_PATTERN.match(line)
    if match is None:
        return None
    return normalize_marker_type(match.group(1)), normalize_marker_id(match.group(2))


def leading_indent(line: str) -> str:
    """Return leading spaces from a line so replacement blocks can preserve indentation."""
    return line[: len(line) - len(line.lstrip(" "))]


def indent_solution_block(lines: list[str], base_indent: str) -> str:
    """Join a block of lines into one multi-line string, prefixed by `base_indent` per line."""
    return "\n".join((f"{base_indent}{line}" if line else "") for line in lines)


def normalized_text_lines(value: Any) -> list[str]:
    """Convert arbitrary payloads (str/list/dict) into normalized printable line strings."""
    if value is None:
        return []

    if isinstance(value, dict):
        lines: list[str] = []
        for key, nested_value in value.items():
            key_text = normalize_inline_text(key)
            if isinstance(nested_value, (dict, list)):
                lines.append(f"{key_text}:")
                nested_lines = normalized_text_lines(nested_value)
                lines.extend([f"  {line}" for line in nested_lines])
            else:
                value_text = normalize_inline_text(nested_value)
                lines.append(
                    f"{key_text}: {value_text}" if value_text else f"{key_text}:"
                )
        return lines

    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            if isinstance(item, (dict, list)):
                nested_lines = normalized_text_lines(item)
                lines.extend([f"  {line}" for line in nested_lines])
            else:
                item_text = normalize_inline_text(item)
                if item_text:
                    lines.append(item_text)
        return lines

    raw_text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return [
        normalized
        for normalized in (normalize_inline_text(line) for line in raw_text.split("\n"))
        if normalized
    ]


###### Solution building functions ######
def build_multiple_choice_solution_string(
    item: dict[str, Any], base_indent: str
) -> str | None:
    """Build an indented `\\solutionline{Answer: ...}` string for one multiple-choice item."""
    answer = normalize_inline_text(item.get("answer"))
    if not answer:
        return None
    return indent_solution_block([rf"\solutionline{{Answer: {answer}}}"], base_indent)


def build_matching_solution_string(
    matching_question: dict[str, Any], base_indent: str
) -> str | None:
    """Build an indented solution block containing the matching-answer two-column table."""
    answers_pairs = matching_question.get("answers_pairs")
    if not isinstance(answers_pairs, dict) or not answers_pairs:
        return None

    block_lines = [
        r"\begin{solutionblock}",
        r"  \solutionheading{Suggested matching answers:}",  # NOTE: soluction heading might not be needed
        "",
        r"  \begin{tabularx}{\linewidth}{|p{0.42\linewidth}|p{0.52\linewidth}|}",
        r"    \hline",
        r"    \textbf{List A Item} & \textbf{Matching List B Item} \\",
        r"    \hline",
    ]
    for list_a_item, list_b_item in answers_pairs.items():
        left = normalize_inline_text(list_a_item)
        right = normalize_inline_text(list_b_item)
        block_lines.append(rf"    {left} & {right} \\")
        block_lines.append(r"    \hline")

    block_lines.extend(
        [
            r"  \end{tabularx}",
            r"\end{solutionblock}",
        ]
    )
    return indent_solution_block(block_lines, base_indent)


def build_question_solution_string(
    question: dict[str, Any], base_indent: str
) -> str | None:
    """Build an indented solution block for Section B/C questions from `answer` payload fields."""
    answer_payload = question.get("answer")
    if not answer_payload:
        return None

    if isinstance(answer_payload, dict):
        example_answer = answer_payload.get("example_answer")
        marking_scheme = answer_payload.get("marking_scheme")
        marking_points = answer_payload.get("marking_points", [])
    else:
        example_answer = answer_payload
        marking_scheme = None
        marking_points = []

    example_answer_lines = normalized_text_lines(example_answer)
    marking_scheme_lines = normalized_text_lines(marking_scheme)
    marking_points_lines = (
        [normalize_inline_text(point) for point in marking_points]
        if isinstance(marking_points, list)
        else []
    )
    marking_points_lines = [line for line in marking_points_lines if line]

    block_lines: list[str] = [r"\begin{solutionblock}"]

    if example_answer_lines:
        block_lines.append(r"  \solutionheading{Suggested answer:}")
        for line in example_answer_lines:
            block_lines.append(rf"  \solutionline{{{line}}}")

    if marking_scheme_lines:
        if len(block_lines) > 1:
            block_lines.append("")
        block_lines.append(r"  \solutionheading{Marking scheme:}")
        for line in marking_scheme_lines:
            block_lines.append(rf"  \solutionline{{{line}}}")

    if marking_points_lines:
        if len(block_lines) > 1:
            block_lines.append("")
        block_lines.append(r"  \solutionheading{Marking points:}")
        block_lines.append(
            r"  \begin{itemize}[leftmargin=1.2em, itemsep=1pt, topsep=2pt]"
        )
        for point in marking_points_lines:
            block_lines.append(rf"    \item {point}")
        block_lines.append(r"  \end{itemize}")

    block_lines.append(r"\end{solutionblock}")
    if block_lines == [r"\begin{solutionblock}", r"\end{solutionblock}"]:
        return None

    return indent_solution_block(block_lines, base_indent)


def build_section_a_solution_lookup(
    section_a_data: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Build Section A lookup maps keyed by normalized marker IDs for fast marker replacement.

    Returns:
        A tuple `(multiple_choice_items_by_id, matching_questions_by_id)`.
    """
    multiple_choice_items_by_id: dict[str, dict[str, Any]] = {}
    matching_questions_by_id: dict[str, dict[str, Any]] = {}

    question_list = section_a_data.get("question_list", [])
    if not isinstance(question_list, list):
        return multiple_choice_items_by_id, matching_questions_by_id

    for question_index, question in enumerate(question_list, start=1):
        if not isinstance(question, dict):
            continue

        question_raw_id = (
            question.get("id")
            if isinstance(question.get("id"), str) and question.get("id").strip()
            else ""
        )
        question_id = normalize_marker_id(question_raw_id)

        items = question.get("items", [])
        if isinstance(items, list):
            for item_index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                item_raw_id = (
                    item.get("id")
                    if isinstance(item.get("id"), str) and item.get("id").strip()
                    else f"{question_raw_id or 'SECTION_A_MULTIPLE_CHOICE'}-item-{item_index}"
                )
                multiple_choice_items_by_id[normalize_marker_id(item_raw_id)] = item

        if isinstance(question.get("answers_pairs"), dict):
            normalized_matching_id = (
                question_id
                if question_id
                else normalize_marker_id("SECTION_A_MATCHING")
            )
            matching_questions_by_id[normalized_matching_id] = question

    return multiple_choice_items_by_id, matching_questions_by_id


def build_question_lookup(
    section_data: dict[str, Any], fallback_id: str
) -> dict[str, dict[str, Any]]:
    """Build a normalized `question_id -> question` map for Section B/C marker resolution."""
    question_by_id: dict[str, dict[str, Any]] = {}
    question_list = section_data.get("question_list", [])
    if not isinstance(question_list, list):
        return question_by_id

    for question_index, question in enumerate(question_list, start=1):
        if not isinstance(question, dict):
            continue
        raw_id = (
            question.get("id")
            if isinstance(question.get("id"), str) and question.get("id").strip()
            else fallback_id
        )
        question_by_id[normalize_marker_id(raw_id)] = question

    return question_by_id


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

    (
        multiple_choice_items_by_id,
        matching_questions_by_id,
    ) = build_section_a_solution_lookup(section_a_data)

    for index, line in enumerate(section_a_lines):
        marker = parse_solution_marker(line)
        if marker is None:
            continue

        marker_type, marker_id = marker
        base_indent = leading_indent(line)
        replacement: str | None = None

        if marker_type == "MULTIPLE_CHOICE":
            item = multiple_choice_items_by_id.get(marker_id)
            if item is None:
                logger.warning(
                    "Section A marker id not found for MULTIPLE_CHOICE: %s", marker_id
                )
            else:
                replacement = build_multiple_choice_solution_string(item, base_indent)

        elif marker_type == "MATCHING":
            matching_question = matching_questions_by_id.get(marker_id)
            if matching_question is None:
                logger.warning(
                    "Section A marker id not found for MATCHING: %s", marker_id
                )
            else:
                replacement = build_matching_solution_string(
                    matching_question, base_indent
                )
        else:
            logger.warning(
                "Unexpected Section A marker type '%s' for marker id '%s'.",
                marker_type,
                marker_id,
            )

        if replacement is None:
            logger.warning(
                "Could not build replacement for Section A marker type='%s' id='%s'. Keeping marker line.",
                marker_type,
                marker_id,
            )
            continue

        section_a_lines[index] = replacement

    return "\n".join(section_a_lines)


def build_solution_section_b(section_b_data: dict[str, Any]) -> str:
    """Build the LaTeX for Section B of the solution PDF, which includes the correct answers and solution explanations.

    Args:
        section_b_data: The JSON data for Section B, including questions, options, correct answers, and solutions.
    Returns:
        A LaTeX string for Section B of the solution PDF, which can include additional formatting to highlight correct answers and solutions.
    """
    section_b_string, section_b_lines = build_section_b(section_b_data)
    if not section_b_string:
        return ""

    question_by_id = build_question_lookup(section_b_data, "SECTION_B_QUESTION")

    for index, line in enumerate(section_b_lines):
        marker = parse_solution_marker(line)
        if marker is None:
            continue

        marker_type, marker_id = marker
        if marker_type != "B_QUESTION":
            logger.warning(
                "Unexpected Section B marker type '%s' for marker id '%s'.",
                marker_type,
                marker_id,
            )
            continue

        question = question_by_id.get(marker_id)
        if question is None:
            logger.warning("Section B marker id not found: %s", marker_id)
            continue

        replacement = build_question_solution_string(question, leading_indent(line))
        if replacement is None:
            logger.warning(
                "Could not build replacement for Section B marker id='%s'. Keeping marker line.",
                marker_id,
            )
            continue

        section_b_lines[index] = replacement

    return "\n".join(section_b_lines)


def build_solution_section_c(section_c_data: dict[str, Any]) -> str:
    """Build the LaTeX for Section C of the solution PDF, which includes the correct answers and solution explanations.

    Args:
        section_c_data: The JSON data for Section C, including questions, options, correct answers, and solutions.
    Returns:
        A LaTeX string for Section C of the solution PDF, which can include additional formatting to highlight correct answers and solutions.
    """
    section_c_string, section_c_lines = build_section_c(section_c_data)
    if not section_c_string:
        return ""

    question_by_id = build_question_lookup(section_c_data, "SECTION_C_QUESTION")

    for index, line in enumerate(section_c_lines):
        marker = parse_solution_marker(line)
        if marker is None:
            continue

        marker_type, marker_id = marker
        if marker_type != "C_QUESTION":
            logger.warning(
                "Unexpected Section C marker type '%s' for marker id '%s'.",
                marker_type,
                marker_id,
            )
            continue

        question = question_by_id.get(marker_id)
        if question is None:
            logger.warning("Section C marker id not found: %s", marker_id)
            continue

        replacement = build_question_solution_string(question, leading_indent(line))
        if replacement is None:
            logger.warning(
                "Could not build replacement for Section C marker id='%s'. Keeping marker line.",
                marker_id,
            )
            continue

        section_c_lines[index] = replacement

    return "\n".join(section_c_lines)


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
