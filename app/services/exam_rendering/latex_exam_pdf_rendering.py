from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.services.latex_image_service import build_latex_document_pdf_at_path

logger = logging.getLogger(__name__)

# color solution text in red in the solution pdf
SOLUTION_COLOR_RGB = (170, 0, 0)

### Functions for normalizing and escaping text for LaTeX output ###
LATEX_ESCAPE_MAP = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


MATH_SEGMENT_PATTERN = re.compile(
    r"(?<!\\)(\$\$.*?(?<!\\)\$\$|\$.*?(?<!\\)\$)",
    re.DOTALL,
)

COMMON_INLINE_MATH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Common structured math commands that should render in math mode even
    # when source text omitted surrounding $...$ delimiters.
    (re.compile(r"\\frac\s*\{[^{}]+\}\s*\{[^{}]+\}"), r"$\g<0>$"),
    (re.compile(r"\\sqrt\s*\{[^{}]+\}"), r"$\g<0>$"),
    # Greek / common symbols that are frequently written without $...$ in source text.
    (re.compile(r"\\pi\b"), r"$\\pi$"),
    (re.compile(r"\\theta\b"), r"$\\theta$"),
    (re.compile(r"\\alpha\b"), r"$\\alpha$"),
    (re.compile(r"\\beta\b"), r"$\\beta$"),
    (re.compile(r"\\gamma\b"), r"$\\gamma$"),
    (re.compile(r"\\lambda\b"), r"$\\lambda$"),
    (re.compile(r"\\mu\b"), r"$\\mu$"),
    (re.compile(r"\\sigma\b"), r"$\\sigma$"),
    (re.compile(r"\\phi\b"), r"$\\phi$"),
    (re.compile(r"\\omega\b"), r"$\\omega$"),
    # Common relation / operator commands.
    (re.compile(r"\\leq?\b"), r"$\\leq$"),
    (re.compile(r"\\geq?\b"), r"$\\geq$"),
    (re.compile(r"\\neq\b"), r"$\\neq$"),
    (re.compile(r"\\times\b"), r"$\\times$"),
    (re.compile(r"\\div\b"), r"$\\div$"),
    (re.compile(r"\\pm\b"), r"$\\pm$"),
]


def latex_escape(value: Any) -> str:
    """Escape LaTeX special characters in a value.

    Args:
        value: Any input value that should be rendered as literal text in LaTeX.

    Returns:
        A LaTeX-safe string with special characters escaped.
    """
    text = "" if value is None else str(value)
    return "".join(LATEX_ESCAPE_MAP.get(char, char) for char in text)


def split_text_and_math_segments(text: str) -> list[tuple[bool, str]]:
    """Split text into plain-text and LaTeX-math segments.

    Args:
        text: Input text that may contain inline (`$...$`) or display
            (`$$...$$`) math segments.

    Returns:
        A list of tuples `(is_math, segment)` where `is_math=True` means
        the segment is math and should be preserved verbatim.
    """
    segments: list[tuple[bool, str]] = []
    cursor = 0

    for match in MATH_SEGMENT_PATTERN.finditer(text):
        if match.start() > cursor:
            segments.append((False, text[cursor : match.start()]))
        segments.append((True, match.group(0)))
        cursor = match.end()

    if cursor < len(text):
        segments.append((False, text[cursor:]))

    if not segments:
        return [(False, text)]

    return segments


def preserve_common_inline_math_symbols(text: str) -> str:
    """Wrap common LaTeX math symbols in plain text with inline math delimiters.

    Args:
        text: Plain (non-math) text segment.

    Returns:
        Text where common symbols like `\\pi` are converted to `$\\pi$`.
    """
    updated = text
    for pattern, replacement in COMMON_INLINE_MATH_PATTERNS:
        updated = pattern.sub(replacement, updated)
    return updated


def normalize_inline_text(value: Any) -> str:
    """Normalize arbitrary text for single-line inline LaTeX usage.

    Args:
        value: Any input value (including None) to normalize.

    Returns:
        A LaTeX-escaped string with normalized whitespace and no newlines.

    Notes:
        The chained `replace(...)` calls fix mixed platform line endings and
        multiline source text before inline insertion:
        - `\\r\\n -> \\n` normalizes Windows newlines.
        - `\\r -> \\n` normalizes legacy Mac-style carriage returns.
        - `\\n -> " "` converts line breaks to spaces so inline contexts (for
          example `\\item ...`) do not get unintended paragraph/line breaks.
        After that, `re.sub(r"\\s+", " ", ...)` collapses repeated whitespace
        (including tabs and adjacent spaces) to keep output clean and stable.
    """
    raw_text = "" if value is None else str(value)
    normalized_line_endings = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    # Some JSON payloads escape math delimiters as '\$...\$'. Convert these
    # into real LaTeX math delimiters before segment parsing.
    normalized_line_endings = normalized_line_endings.replace(r"\$", "$")

    segments = split_text_and_math_segments(normalized_line_endings)
    normalized_segments: list[str] = []

    for is_math, segment in segments:
        if is_math:
            # Preserve LaTeX math content exactly (including backslashes, braces, ^, _).
            normalized_segments.append(segment)
            continue

        # In plain text, first promote common math symbols (e.g. \pi) to math mode.
        with_promoted_symbols = preserve_common_inline_math_symbols(segment)

        # Protect promoted inline math placeholders from escaping.
        plain_parts = split_text_and_math_segments(with_promoted_symbols)
        escaped_parts: list[str] = []
        for part_is_math, part in plain_parts:
            if part_is_math:
                escaped_parts.append(part)
            else:
                escaped_parts.append(latex_escape(part))
        escaped = "".join(escaped_parts)

        escaped = escaped.replace("\n", " ")
        escaped = re.sub(r"\s+", " ", escaped)
        normalized_segments.append(escaped)

    return "".join(normalized_segments).strip()


def split_lines(value: Any) -> list[str]:
    """Split text into non-empty trimmed lines.

    Args:
        value: Any value containing line breaks.

    Returns:
        A list of non-empty lines with surrounding whitespace removed.
    """
    text = "" if value is None else str(value)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return [line.strip() for line in normalized.split("\n") if line.strip()]


def normalize_multiple_choice_option_text(option: Any) -> str:
    """Normalize multiple-choice option text for LaTeX list rendering.

    Args:
        option: Option payload, either a dict with `text` or a raw string-like value.

    Returns:
        A normalized inline string without leading option labels (e.g., `A.`, `B:`).
    """
    raw = option.get("text", "") if isinstance(option, dict) else str(option)
    # Remove a leading option label like "A. " or "B) " because LaTeX renders labels.
    label_pattern = re.compile(r"^\s*[A-Za-z]\s*[\.\):]\s*")
    while True:
        updated = label_pattern.sub("", raw, count=1)
        if updated == raw:
            break
        raw = updated
    return normalize_inline_text(raw)


### Functions to build each part of the LaTeX document from JSON data ###
def build_document_start() -> str:
    """Build the static LaTeX preamble and document start. This includes packages and custom commands
    for the exam and exam solution pdf for easier modification. Unused packages and commands in the latex
    document have no effect on the generated pdf, so for simplicity we use a common preamble for both exam
    and solution documents.

    Returns:
        The full preamble string ending at `\\begin{document}`.
    """
    doc_start_items = [
        r"\documentclass[12pt]{article}",
        " ",
        r"\usepackage[a4paper, margin=1in]{geometry}",
        r"\usepackage{enumitem}",
        r"\usepackage{multicol}",
        r"\usepackage{amsmath}",
        r"\usepackage{times}",
        r"\usepackage{fancyhdr}",
        r"\usepackage{tabularx}",
        r"\usepackage{needspace}",
        r"\usepackage{xcolor}",
        " ",
        r"\pagestyle{fancy}",
        r"\fancyhf{}",
        r"\renewcommand{\headrulewidth}{0pt}",
        r"\renewcommand{\footrulewidth}{0pt}",
        r"\fancyfoot[R]{Page \thepage}",
        r"\fancyfoot[L]{Twiga Generated Practice Exam}",
        " ",
        r"\newcommand{\leftheading}[1]{",
        r"    \noindent{\fontsize{12}{14}\selectfont\bfseries #1}\par",
        r"}",
        " ",
        r"\newcommand{\centerheading}[1]{",
        r"    \vspace{0.6em}",
        r"    \begin{center}",
        r"        {\fontsize{13}{15}\selectfont\bfseries #1}",
        r"    \end{center}",
        r"    \vspace{0.15em}",
        r"}",
        " ",
        r"\newenvironment{questionblock}[1][10]{",
        r"    \par\Needspace{#1\baselineskip}",
        r"}{",
        r"    \par",
        r"}",
        " ",
        r"% defining the solution text color and layout commands",
        rf"\definecolor{{solutionred}}{{RGB}}{{{SOLUTION_COLOR_RGB[0]},{SOLUTION_COLOR_RGB[1]},{SOLUTION_COLOR_RGB[2]}}}",
        r"\newcommand{\solutionheading}[1]{",
        r"    \par{\color{solutionred}\textbf{#1}}\par",
        r"}",
        r"\newcommand{\solutionline}[1]{",
        r"    \par{\color{solutionred}#1}\par",
        r"}",
        r"\newenvironment{solutionblock}{",
        r"    \par\begingroup\color{solutionred}",
        r"}{",
        r"    \par\endgroup",
        r"}",
        " ",
        r"\begin{document}",
    ]
    return "\n".join(doc_start_items)


def build_header(meta: dict[str, Any]) -> str:
    """Build the exam header block from metadata.

    Args:
        meta: Metadata dictionary containing country, office, exam title, subject,
            duration, and year fields.

    Returns:
        A LaTeX header block with centered title lines and time/year row.
    """
    country = normalize_inline_text(meta.get("country", ""))
    office_lines = [
        normalize_inline_text(line) for line in split_lines(meta.get("office", ""))
    ]
    exam_title = normalize_inline_text(meta.get("exam_title", ""))
    subject = normalize_inline_text(meta.get("subject", ""))
    duration = normalize_inline_text(meta.get("duration", ""))
    year = normalize_inline_text(meta.get("year", ""))

    lines: list[str] = []
    lines.append(r"\begin{center}")
    if country:
        lines.append(rf"  {{\fontsize{{14}}{{16}}\selectfont\bfseries {country}\par}}")
    lines.append(r"  \vspace{0.2em}")
    for office_line in office_lines:
        lines.append(rf"  {{\fontsize{{12}}{{14}}\selectfont {office_line}\par}}")
    lines.append(r"  \vspace{0.35em}")
    if exam_title:
        lines.append(
            rf"  {{\fontsize{{14}}{{16}}\selectfont\bfseries {exam_title}\par}}"
        )
    if subject:
        lines.append(rf"  {{\fontsize{{14}}{{16}}\selectfont\bfseries {subject}\par}}")
    lines.append(r"\end{center}")
    lines.append(r"\vspace{0.6em}")
    lines.append(
        rf"\noindent{{\fontsize{{12}}{{14}}\selectfont Time: {duration}\hfill YEAR: {year}\par}}"
    )
    lines.append(r"\vspace{0.8em}")
    # add divider line after header
    lines.append("")
    lines.append(r"\vspace{-1.0em}")
    lines.append(r"\noindent\rule{\textwidth}{0.4pt}")
    lines.append(r"\vspace{-1.0em}")
    return "\n".join(lines)


def build_instructions(instructions: list[Any]) -> str:
    """Build the instructions section as a compact numbered list.

    Args:
        instructions: Sequence of instruction strings.

    Returns:
        LaTeX for the `INSTRUCTIONS` heading and its enumerate block.
    """
    lines: list[str] = []
    lines.append(r"\leftheading{INSTRUCTIONS}")
    lines.append(
        r"\begin{enumerate}[itemsep=0pt, topsep=2pt, parsep=0pt, partopsep=0pt]"
    )
    for instruction in instructions:
        lines.append(rf"  \item {normalize_inline_text(instruction)}")
    lines.append(r"\end{enumerate}")
    return "\n".join(lines)


def is_multiple_choice(question: dict[str, Any]) -> bool:
    """Determine whether a question payload is multiple-choice.

    Args:
        question: A question dictionary from JSON.

    Returns:
        True when the question is typed as multiple-choice or has `items`.
    """
    question_type = str(question.get("type") or "").strip().lower()
    return question_type == "multiple_choice"


def extract_matching_lists(question: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    """Extract List A and List B values from a matching question.

    Args:
        question: A question dictionary that may contain `listA/listB` or
            `list_a/list_b`.

    Returns:
        A tuple `(list_a, list_b)` where both elements are lists.
    """
    list_a = question.get("listA")
    list_b = question.get("listB")

    if not isinstance(list_a, list):
        list_a = question.get("list_a")
    if not isinstance(list_b, list):
        list_b = question.get("list_b")

    return (
        list_a if isinstance(list_a, list) else [],
        list_b if isinstance(list_b, list) else [],
    )


def is_matching(question: dict[str, Any]) -> bool:
    """Determine whether a question payload should be treated as matching.

    Args:
        question: A question dictionary from JSON.

    Returns:
        True when matching lists exist or type is explicitly `item_matching`.
    """
    question_type = str(question.get("type") or "").strip().lower()
    return question_type == "item_matching"


def apply_indentation(line: str, level: int) -> str:
    """Apply indentation to a line based on the specified level.

    Args:
        line: The input line to indent.
        level: The indentation level (number of indentations to apply, 2 spaces per level).

    Returns:
        The indented line with spaces corresponding to the indentation level.
    """
    indent = " " * (level * 2)
    return indent + line


def build_solution_marker(marker_type: str, marker_id: str) -> str:
    """Build a stable LaTeX comment marker for later solution replacement."""
    normalized_type = re.sub(r"[^A-Z0-9_]", "_", str(marker_type).upper())
    normalized_id = re.sub(r"[^A-Za-z0-9_.:\-]", "_", str(marker_id))
    return f"%<TWIGA_SOLUTION:type={normalized_type};id={normalized_id}>"


def build_multiple_choice_block(
    question: dict[str, Any], multiple_choice_marks: int
) -> list[str]:
    """Build LaTeX for a full multiple-choice question block in Section A.

    Args:
        question: Multiple-choice question dictionary with prompt and `items`.
        multiple_choice_marks: Section-level marks.

    Returns:
        A list of LaTeX lines for the numbered question, roman sub-items, and A-E options.
    """
    base_indent_level = 1
    prompt = normalize_inline_text(question.get("prompt", ""))
    items = question.get("items", [])
    question_id = (
        str(question.get("id")).strip()
        if isinstance(question.get("id"), str) and question.get("id").strip()
        else "SECTION_A_MULTIPLE_CHOICE"
    )

    lines: list[str] = []
    lines.append(
        apply_indentation(
            line=rf"\item {prompt} \textbf{{({multiple_choice_marks} Marks)}}",
            level=base_indent_level,
        )
    )
    lines.append("")
    lines.append(
        apply_indentation(
            line=r"\begin{enumerate}[label=(\roman*)]", level=base_indent_level
        )
    )
    lines.append("")

    for item_idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue

        item_question = normalize_inline_text(item.get("question", ""))
        options = item.get("options", [])
        item_id = (
            str(item.get("id")).strip()
            if isinstance(item.get("id"), str) and item.get("id").strip()
            else f"{question_id}-item-{item_idx}"
        )

        lines.append(
            apply_indentation(
                line=r"\begin{questionblock}", level=base_indent_level + 1
            )
        )
        lines.append(
            apply_indentation(
                line=rf"\item {item_question}", level=base_indent_level + 2
            )
        )
        lines.append(
            apply_indentation(
                line=r"\begin{enumerate}[label=\Alph*.]", level=base_indent_level + 2
            )
        )

        for option in options:
            lines.append(
                apply_indentation(
                    line=rf"\item {normalize_multiple_choice_option_text(option)}",
                    level=base_indent_level + 3,
                )
            )

        lines.append(
            apply_indentation(line=r"\end{enumerate}", level=base_indent_level + 2)
        )
        lines.append(
            apply_indentation(
                line=build_solution_marker("MULTIPLE_CHOICE", item_id),
                level=base_indent_level + 2,
            )
        )
        lines.append(
            apply_indentation(line=r"\vspace{0.8em}", level=base_indent_level + 2)
        )
        lines.append(
            apply_indentation(line=r"\end{questionblock}", level=base_indent_level + 1)
        )
        lines.append("")

    lines.append(apply_indentation(line=r"\end{enumerate}", level=base_indent_level))

    return lines


def build_matching_block(question: dict[str, Any], matching_marks: int) -> list[str]:
    """Build LaTeX for a full matching question block in Section A.

    Args:
        question: Matching question dictionary containing prompt and list pairs.
        matching_marks: Section-level marks value to display in heading.

    Returns:
        A list of LaTeX lines for the matching question with two tabularx columns (List A/B).
    """
    base_indent_level = 1
    prompt = normalize_inline_text(question.get("prompt", ""))
    list_a, list_b = extract_matching_lists(question)
    question_id = (
        str(question.get("id")).strip()
        if isinstance(question.get("id"), str) and question.get("id").strip()
        else "SECTION_A_MATCHING"
    )

    lines: list[str] = []
    lines.append(
        apply_indentation(line=r"\begin{questionblock}[24]", level=base_indent_level)
    )
    lines.append(
        apply_indentation(
            line=rf"\item {prompt} \textbf{{({matching_marks} Marks)}}\par",
            level=base_indent_level,
        )
    )
    lines.append(apply_indentation(line=r"\vspace{0.35em}", level=base_indent_level))
    lines.append(
        apply_indentation(
            line=r"\noindent\begin{tabularx}{\linewidth}{@{}p{0.48\linewidth}p{0.48\linewidth}@{}}",
            level=base_indent_level,
        )
    )
    lines.append(
        apply_indentation(
            line=r"\textbf{List A} & \textbf{List B} \\", level=base_indent_level + 1
        )
    )
    lines.append(
        apply_indentation(line=r"\noalign{\vskip 0.15em}", level=base_indent_level + 1)
    )
    lines.append(apply_indentation(line=r"\hline", level=base_indent_level + 1))
    lines.append(
        apply_indentation(line=r"\noalign{\vskip 0.15em}", level=base_indent_level + 1)
    )
    lines.append(
        apply_indentation(
            line=r"\begin{minipage}[t]{\linewidth}", level=base_indent_level + 1
        )
    )
    lines.append(
        apply_indentation(
            line=r"\begin{enumerate}[label=(\roman*), leftmargin=*, itemsep=0.35em, topsep=0.35em, parsep=0pt]",
            level=base_indent_level + 2,
        )
    )
    for item in list_a:
        lines.append(
            apply_indentation(
                line=rf"\item {normalize_inline_text(item)}",
                level=base_indent_level + 3,
            )
        )
    lines.append(
        apply_indentation(line=r"\end{enumerate}", level=base_indent_level + 2)
    )
    lines.append(apply_indentation(line=r"\end{minipage}", level=base_indent_level + 1))
    lines.append(apply_indentation(line=r"&", level=base_indent_level + 1))
    lines.append(
        apply_indentation(
            line=r"\begin{minipage}[t]{\linewidth}", level=base_indent_level + 1
        )
    )
    lines.append(
        apply_indentation(
            line=r"\begin{enumerate}[label=\Alph*., leftmargin=*, itemsep=0.35em, topsep=0.35em, parsep=0pt]",
            level=base_indent_level + 2,
        )
    )
    for item in list_b:
        lines.append(
            apply_indentation(
                line=rf"\item {normalize_inline_text(item)}",
                level=base_indent_level + 3,
            )
        )
    lines.append(
        apply_indentation(line=r"\end{enumerate}", level=base_indent_level + 2)
    )
    lines.append(apply_indentation(line=r"\end{minipage}", level=base_indent_level + 1))
    lines.append(apply_indentation(line=r"\end{tabularx}", level=base_indent_level))
    lines.append(
        apply_indentation(
            line=build_solution_marker("MATCHING", question_id),
            level=base_indent_level,
        )
    )
    lines.append(
        apply_indentation(line=r"\end{questionblock}", level=base_indent_level)
    )
    return lines


def build_section_a(section_a: dict[str, Any]) -> tuple[str, list[str]]:
    """Build the complete Section A block from JSON data.

    Args:
        section_a: Section A dictionary containing title, instructions, marks,
            and `question_list`.

    Returns:
        A tuple of `(section_text, lines)`, where `section_text` is the rendered
        LaTeX for Section A and `lines` is the list used to build it. Returns
        `("", [])` when no Section A questions exist.
    """
    question_list = section_a.get("question_list")
    if not isinstance(question_list, list) or not question_list:
        return "", []

    section_title = normalize_inline_text(section_a.get("section_title", "SECTION A"))
    section_instructions = normalize_inline_text(
        section_a.get("section_instructions", "")
    )
    multiple_choice_marks = int(section_a.get("multiple_choice_marks", 0))
    matching_marks = int(section_a.get("matching_marks", 0))
    total_section_a_marks = multiple_choice_marks + matching_marks

    lines: list[str] = []
    lines.append(r"% section A")
    lines.append(rf"\centerheading{{{section_title} ({total_section_a_marks} Marks)}}")
    lines.append(r"\vspace{-2.0em}")
    lines.append(r"\begin{center}")
    lines.append(apply_indentation(line=section_instructions, level=1))
    lines.append(r"\end{center}")
    lines.append("")

    lines.append(r"\begin{enumerate}")

    # place all the multiple choice questions first, then the matching questions
    for question in question_list:
        if not isinstance(question, dict):
            continue
        if is_multiple_choice(question):
            lines.extend(build_multiple_choice_block(question, multiple_choice_marks))
            lines.append("")

    for question in question_list:
        if not isinstance(question, dict):
            continue

        if is_matching(question):
            lines.extend(build_matching_block(question, matching_marks))
            lines.append("")

    lines.append(r"\end{enumerate}")
    return "\n".join(lines), lines


def build_section_b_sub_question_block(
    sub_question: dict[str, Any], indent_level: int
) -> list[str]:
    """Build LaTeX for a single sub-question within a Section B part.

    Args:
        sub_question: A sub-question dictionary containing `text` and `marks`.
        indent_level: The indentation level to apply for this sub-question.
    Returns:
        A list of LaTeX lines for the sub-question as a roman-labeled item.
    """
    part_label = normalize_inline_text(sub_question.get("label", ""))
    part_prompt = normalize_inline_text(sub_question.get("prompt", ""))
    part_marks = int(sub_question.get("marks") or 0)
    part_sub_questions = sub_question.get("sub_questions", [])

    part_heading = f"({part_label}) {part_prompt} ({part_marks})"

    lines: list[str] = []
    lines.append(apply_indentation(line=part_heading, level=indent_level))

    # (might have sub-questions)
    if part_sub_questions:
        lines.append(
            apply_indentation(
                line=r"\begin{enumerate}[label=(\roman*)]", level=indent_level
            )
        )

        for sub_question in part_sub_questions:
            sub_text = normalize_inline_text(
                sub_question.get("text", sub_question.get("prompt", ""))
            )
            sub_marks = int(sub_question.get("marks") or 0)

            sub_text = f"{sub_text} ({sub_marks})"

            lines.append(
                apply_indentation(line=rf"\item {sub_text}", level=indent_level + 1)
            )

        lines.append(apply_indentation(line=r"\end{enumerate}", level=indent_level))

    return lines


def build_section_b_block(question: dict[str, Any]) -> list[str]:
    """Build LaTeX for one Section B question block.

    Args:
        question: A question dictionary from Section B.

    Returns:
        A list of LaTeX lines for one top-level Section B item including
        optional parts and optional sub-questions.
    """
    if not isinstance(question, dict):
        return []

    base_indent_level = 1
    question_marks = int(question.get("marks") or 0)
    parts = question.get("parts", [])
    question_id = (
        str(question.get("id")).strip()
        if isinstance(question.get("id"), str) and question.get("id").strip()
        else "SECTION_B_QUESTION"
    )

    if len(parts) == 0:
        return []  # No content to render for this question

    lines: list[str] = []
    lines.append(
        apply_indentation(line=r"\begin{questionblock}[15]", level=base_indent_level)
    )

    lines.append(
        apply_indentation(
            line=rf"\item \textbf{{({question_marks} Marks)}}" + "\n",
            level=base_indent_level + 1,
        )
    )

    for part in parts:
        if not isinstance(part, dict):
            continue

        lines.extend(
            build_section_b_sub_question_block(
                sub_question=part,
                indent_level=base_indent_level + 1,
            )
        )
        lines.append("")
    else:
        if len(parts) > 0:
            lines.pop()  # remove last extra newline if no more parts to add

    lines.append(
        apply_indentation(
            line=build_solution_marker("B_QUESTION", question_id),
            level=base_indent_level + 1,
        )
    )
    lines.append(
        apply_indentation(line=r"\end{questionblock}", level=base_indent_level)
    )

    return lines


def build_section_b(section_b: dict[str, Any]) -> tuple[str, list[str]]:
    """Build the complete Section B block from JSON data.

    Args:
        section_b: Section B dictionary from JSON.

    Returns:
        A tuple of `(section_text, lines)`, where `section_text` is the rendered
        LaTeX for Section B and `lines` is the list used to build it. Returns
        `("", [])` when no Section B questions exist.
    """
    question_list = section_b.get("question_list")
    if not isinstance(question_list, list) or not question_list:
        return "", []

    section_title = normalize_inline_text(section_b.get("section_title", "SECTION B"))
    section_instructions = normalize_inline_text(
        section_b.get("section_instructions", "")
    )
    section_marks = int(section_b.get("marks") or 0)
    section_heading = f"{section_title} ({section_marks} Marks)"

    lines: list[str] = []
    lines.append(r"% section B")
    lines.append(r"\Needspace{21\baselineskip}")
    lines.append(rf"\centerheading{{{section_heading}}}")
    lines.append(r"\vspace{-2.0em}")
    lines.append(r"\begin{center}")
    lines.append(apply_indentation(line=section_instructions, level=1))
    lines.append(r"\end{center}")
    lines.append(r"\vspace{-2.0em}")
    lines.append("")
    lines.append(r"\begin{enumerate}[start=3]")

    for question in question_list:
        if not isinstance(question, dict):
            continue

        lines.extend(build_section_b_block(question))
        lines.append("")

    lines.append(r"\end{enumerate}")
    return "\n".join(lines), lines


def build_section_c_block(question: dict[str, Any]) -> list[str]:
    """Build LaTeX for one Section C question block.

    Args:
        question: A question dictionary from Section C.

    Returns:
        A list of LaTeX lines for one top-level Section C item with optional
        task prompt and optional task sub-questions.
    """
    if not isinstance(question, dict):
        return []

    base_indent_level = 1
    question_marks = int(question.get("marks") or 0)
    description = normalize_inline_text(question.get("description", ""))
    task = question.get("task", {})
    question_id = (
        str(question.get("id")).strip()
        if isinstance(question.get("id"), str) and question.get("id").strip()
        else "SECTION_C_QUESTION"
    )

    if isinstance(task, dict):
        task_prompt = normalize_inline_text(task.get("prompt", ""))
        sub_questions = task.get("sub_questions", [])
    else:
        task_prompt = ""
        sub_questions = []

    task_description_prompt = f"{description} {task_prompt}"

    lines: list[str] = []
    lines.append(
        apply_indentation(line=r"\begin{questionblock}[10]", level=base_indent_level)
    )
    lines.append(
        apply_indentation(
            line=rf"\item {task_description_prompt} \textbf{{({question_marks} Marks)}}",
            level=base_indent_level + 1,
        )
    )
    if sub_questions:
        lines.append(
            apply_indentation(line=r"\begin{enumerate}", level=base_indent_level + 1)
        )
        for sub_question in sub_questions:
            sub_prompt = normalize_inline_text(sub_question.get("prompt", ""))
            sub_marks = int(sub_question.get("marks") or 0)
            lines.append(
                apply_indentation(
                    line=rf"\item {sub_prompt} ({sub_marks})",
                    level=base_indent_level + 2,
                )
            )

        lines.append(
            apply_indentation(line=r"\end{enumerate}", level=base_indent_level + 1)
        )

    lines.append(
        apply_indentation(
            line=build_solution_marker("C_QUESTION", question_id),
            level=base_indent_level + 1,
        )
    )
    lines.append(
        apply_indentation(line=r"\end{questionblock}", level=base_indent_level)
    )

    return lines


def build_section_c(section_c: dict[str, Any]) -> tuple[str, list[str]]:
    """Build the complete Section C block from JSON data.

    Args:
        section_c: Section C dictionary from JSON.

    Returns:
        A tuple of `(section_text, lines)`, where `section_text` is the rendered
        LaTeX for Section C and `lines` is the list used to build it. Returns
        `("", [])` when no Section C questions exist.
    """
    question_list = section_c.get("question_list")
    if not isinstance(question_list, list) or not question_list:
        return "", []

    section_title = normalize_inline_text(section_c.get("section_title", "SECTION C"))
    section_instructions = normalize_inline_text(
        section_c.get("section_instructions", "")
    )
    section_marks = int(section_c.get("marks") or 0)
    section_heading = f"{section_title} ({section_marks} Marks)"
    section_start = 13

    lines: list[str] = []
    lines.append(r"% section C")
    lines.append(r"\Needspace{16\baselineskip}")
    lines.append(rf"\centerheading{{{section_heading}}}")
    lines.append(r"\vspace{-2.0em}")
    lines.append(r"\begin{center}")
    lines.append(apply_indentation(line=section_instructions, level=1))
    lines.append(r"\end{center}")
    lines.append(r"\vspace{-1.5em}")
    lines.append("")
    lines.append(rf"\begin{{enumerate}}[start={section_start}]")

    for question in question_list:
        if not isinstance(question, dict):
            continue

        lines.extend(build_section_c_block(question))
        lines.append("")

    lines.append(r"\end{enumerate}")
    return "\n".join(lines), lines


def build_document_end() -> str:
    """Build the LaTeX document closing tag.

    Returns:
        A string containing `\\end{document}`.
    """
    return r"\end{document}"


def build_exam_document(data: dict[str, Any]) -> str:
    """Assemble the full LaTeX document from parsed JSON exam data.

    Args:
        data: Full exam JSON dictionary.

    Returns:
        A complete LaTeX document string ready to write to disk.
    """
    section_a_text, _ = build_section_a(data.get("section_A", {}))
    section_b_text, _ = build_section_b(data.get("section_B", {}))
    section_c_text, _ = build_section_c(data.get("section_C", {}))

    parts = [
        build_document_start(),
        build_header(data.get("meta", {})),
        build_instructions(data.get("instructions", [])),
        section_a_text,
        section_b_text,
        section_c_text,
        build_document_end(),
    ]
    return "\n\n".join(part for part in parts if part.strip()) + "\n"


######## Interface function ###########
def build_latex_exam_pdf(exam: dict[str, Any], out_path: str | Path) -> None:
    """
    Build a LaTeX exam PDF from JSON exam data.

    Args:
        exam: The exam data in JSON format.
        out_path: The path where the generated PDF will be saved.
    """
    try:
        latex_doc = build_exam_document(exam)
    except Exception as e:
        logger.error(f"Error building LaTeX document string: {e}")
        raise RuntimeError("Failed to build LaTeX document string") from e

    logger.debug(f"Generated LaTeX document string:\n{latex_doc}")

    try:
        build_latex_document_pdf_at_path(
            latex_document=latex_doc,
            out_path=out_path,
        )
    except Exception as e:
        logger.error(f"Error building LaTeX exam PDF: {e}")
        raise RuntimeError("Failed to build LaTeX exam PDF from document string")
