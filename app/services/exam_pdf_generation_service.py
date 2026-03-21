import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def safe_text(value: Any) -> str:
    """Convert values to clean printable text."""
    if value is None:
        return ""

    text = str(value)
    replacements = {
        "\u2011": "-",
        "â€™": "'",
        "â€˜": "'",
        "â€œ": '"',
        "â€\u009d": '"',
        "â€“": "-",
        "â€”": "-",
    }
    for raw, fixed in replacements.items():
        text = text.replace(raw, fixed)

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def p(text: Any, style: ParagraphStyle) -> Paragraph:
    """Build a paragraph with escaped text and preserved line breaks."""
    normalized = safe_text(text)
    if not normalized:
        return Paragraph("", style)
    return Paragraph(escape(normalized).replace("\n", "<br/>"), style)


def p_markup(markup_text: str, style: ParagraphStyle) -> Paragraph:
    """Build a paragraph from trusted ReportLab markup."""
    return Paragraph(markup_text, style)


def marks_suffix(marks: Any) -> str:
    marks_text = safe_text(marks)
    return f" ({marks_text} marks)" if marks_text else ""


def question_heading_markup(question_number: int, marks: Any, prompt: str = "") -> str:
    """Create a heading with a bold question number and optional marks."""
    markup = f"<b>{question_number}.</b>"
    suffix = marks_suffix(marks)
    if suffix:
        markup = f"{markup}<b>{escape(suffix)}</b>"
    prompt_text = safe_text(prompt)
    if prompt_text:
        markup = f"{markup} {escape(prompt_text)}"
    return markup


def append_question_block(
    story: List[Any],
    block: List[Any],
    spacer_height: int,
    *,
    keep_together: bool = True,
) -> None:
    if not block:
        return
    if keep_together:
        story.append(KeepTogether(block))
    else:
        story.extend(block)
    story.append(Spacer(1, spacer_height))


def section_a_heading_markup(question_number: int, prompt: str, marks: Any) -> str:
    markup = f"<b>{question_number}.</b>"
    prompt_text = safe_text(prompt)
    if prompt_text:
        markup = f"{markup} {escape(prompt_text)}"
    suffix = marks_suffix(marks)
    if suffix:
        markup = f"{markup}<b>{escape(suffix)}</b>"
    return markup


def roman_like_label(index: int) -> str:
    labels = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
    if 1 <= index <= len(labels):
        return labels[index - 1]
    return str(index)


def extract_question_number(question: Dict[str, Any], fallback: int) -> int:
    question_id = safe_text(question.get("id"))
    match = re.search(r"Q(\d+)", question_id)
    if match:
        return int(match.group(1))
    return fallback


def detect_section_a_question_type(question: Dict[str, Any]) -> str:
    """Infer Section A question type when `type` is missing in JSON."""
    explicit_type = safe_text(question.get("type", "")).lower()
    if explicit_type:
        return explicit_type

    items = question.get("items")
    if isinstance(items, list) and items:
        return "multiple_choice"

    list_a = question.get("listA")
    list_b = question.get("listB")
    if isinstance(list_a, list) and isinstance(list_b, list):
        return "item_matching"

    return ""


def sort_questions(questions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    indexed = list(enumerate(list(questions)))
    indexed.sort(
        key=lambda pair: (extract_question_number(pair[1], pair[0] + 1), pair[0])
    )
    return [item for _, item in indexed]


def normalize_option_text(label: str, text: str) -> str:
    label_prefix = re.compile(
        rf"^{re.escape(label)}\s*[\.\):]\s*",
        flags=re.IGNORECASE,
    )
    return label_prefix.sub("", safe_text(text))


def normalize_mcq_options(raw_options: Any) -> List[Tuple[str, str]]:
    if isinstance(raw_options, dict):
        options: List[Tuple[str, str]] = []
        for label in ["A", "B", "C", "D", "E"]:
            if label in raw_options:
                options.append(
                    (label, normalize_option_text(label, raw_options[label]))
                )
        return options

    if not isinstance(raw_options, list):
        return []

    options = []
    for idx, option in enumerate(raw_options):
        if isinstance(option, dict):
            label = safe_text(option.get("label")) or chr(ord("A") + idx)
            text = safe_text(option.get("text"))
        else:
            label = chr(ord("A") + idx)
            text = safe_text(option)
        options.append((label.upper(), normalize_option_text(label, text)))
    return options


def normalize_list_entries(raw_items: Any, label_style: str) -> List[Tuple[str, str]]:
    if not isinstance(raw_items, list):
        return []

    normalized: List[Tuple[str, str]] = []
    for idx, item in enumerate(raw_items, start=1):
        if isinstance(item, dict):
            label = safe_text(item.get("label"))
            text = safe_text(item.get("text"))
        else:
            label = ""
            text = safe_text(item)

        if not label:
            if label_style == "roman":
                label = roman_like_label(idx)
            else:
                label = chr(ord("A") + idx - 1)
        normalized.append((label, text))
    return normalized


def format_answer_lines(value: Any, prefix: str = "") -> List[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        lines: List[str] = []
        for key, sub_value in value.items():
            key_text = safe_text(key)
            next_prefix = f"{prefix}{key_text}: " if prefix else f"{key_text}: "
            if isinstance(sub_value, (dict, list)):
                lines.append(next_prefix.rstrip())
                lines.extend(format_answer_lines(sub_value, prefix="  "))
            else:
                lines.append(f"{next_prefix}{safe_text(sub_value)}")
        return lines
    if isinstance(value, list):
        lines = []
        for idx, item in enumerate(value, start=1):
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{idx}.")
                lines.extend(format_answer_lines(item, prefix="  "))
            else:
                lines.append(f"{prefix}{idx}. {safe_text(item)}")
        return lines
    return [f"{prefix}{safe_text(value)}"]


@dataclass(frozen=True)
class Styles:
    base: ParagraphStyle
    title: ParagraphStyle
    center: ParagraphStyle
    bold: ParagraphStyle
    section_header: ParagraphStyle
    small: ParagraphStyle
    part: ParagraphStyle
    subpart: ParagraphStyle
    answer: ParagraphStyle
    answer_heading: ParagraphStyle


def build_styles() -> Styles:
    styles = getSampleStyleSheet()

    base = styles["Normal"]
    base.fontName = "Times-Roman"
    base.fontSize = 11
    base.leading = 14

    title = ParagraphStyle(
        "Title",
        parent=base,
        fontName="Times-Bold",
        fontSize=12.5,
        leading=16,
        alignment=1,
        spaceAfter=6,
    )
    center = ParagraphStyle(
        "Center",
        parent=base,
        alignment=1,
        spaceAfter=2,
    )
    bold = ParagraphStyle(
        "Bold",
        parent=base,
        fontName="Times-Bold",
    )
    section_header = ParagraphStyle(
        "SectionHeader",
        parent=base,
        fontName="Times-Bold",
        fontSize=12,
        alignment=1,
        spaceBefore=10,
        spaceAfter=6,
    )
    small = ParagraphStyle(
        "Small",
        parent=base,
        fontSize=10,
        leading=12,
    )
    part = ParagraphStyle(
        "Part",
        parent=base,
        leftIndent=6,
        spaceBefore=1,
    )
    subpart = ParagraphStyle(
        "SubPart",
        parent=base,
        leftIndent=14,
        spaceBefore=1,
    )
    answer = ParagraphStyle(
        "Answer",
        parent=base,
        textColor=colors.darkred,
        fontName="Times-Italic",
        leftIndent=8,
        spaceAfter=1,
    )
    answer_heading = ParagraphStyle(
        "AnswerHeading",
        parent=base,
        fontName="Times-BoldItalic",
        textColor=colors.darkred,
        spaceBefore=3,
        spaceAfter=1,
    )

    return Styles(
        base=base,
        title=title,
        center=center,
        bold=bold,
        section_header=section_header,
        small=small,
        part=part,
        subpart=subpart,
        answer=answer,
        answer_heading=answer_heading,
    )


def render_header(
    story: List[Any], exam: Dict[str, Any], st: Styles, is_solution: bool
) -> None:
    meta = exam.get("meta", {})

    country = safe_text(meta.get("country", ""))
    office = safe_text(meta.get("office", ""))

    if country:
        story.append(p(country, st.title))
    if office:
        for line in office.split("\n"):
            story.append(p(line, st.center))

    story.append(Spacer(1, 5))

    exam_title = safe_text(meta.get("exam_title", ""))
    if is_solution and exam_title:
        exam_title = f"{exam_title} - MARKING SCHEME / SOLUTION KEY"

    subject = safe_text(meta.get("subject", ""))
    duration = safe_text(meta.get("duration", ""))
    year = safe_text(meta.get("year", ""))

    if exam_title:
        story.append(p(exam_title, st.title))
    if subject:
        story.append(p(subject, st.title))

    time_year_table = Table(
        [[f"Time: {duration}", f"YEAR: {year}"]], colWidths=[80 * mm, 80 * mm]
    )
    time_year_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Times-Roman"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(time_year_table)
    story.append(
        HRFlowable(
            width="100%", thickness=1, color=colors.black, spaceBefore=0, spaceAfter=0
        )
    )
    story.append(Spacer(1, 6))


def render_instructions(story: List[Any], exam: Dict[str, Any], st: Styles) -> None:
    instructions = exam.get("instructions", [])
    if not instructions:
        return

    story.append(p("INSTRUCTIONS", st.bold))
    for idx, line in enumerate(instructions, start=1):
        story.append(p(f"{idx}. {line}", st.base))
    story.append(Spacer(1, 6))


def render_constants(story: List[Any], exam: Dict[str, Any], st: Styles) -> None:
    constants = exam.get("constants", {})
    if not isinstance(constants, dict) or not constants:
        return

    lines: List[str] = []
    atomic_masses = constants.get("atomic_masses", {})
    if isinstance(atomic_masses, dict) and atomic_masses:
        pairs = [f"{key} = {atomic_masses[key]}" for key in atomic_masses.keys()]
        lines.append("Atomic masses: " + ", ".join(pairs))

    mapping = [
        ("avogadro", "Avogadro's number"),
        ("gmv_stp", "GMV at s.t.p"),
        ("faraday", "1 Faraday"),
        ("std_temp", "Standard temperature"),
        ("litre_equiv", ""),
    ]

    for key, label in mapping:
        value = constants.get(key)
        if not value:
            continue
        if key == "litre_equiv":
            lines.append(safe_text(value))
        else:
            lines.append(f"{label} = {value}")

    if not lines:
        return

    story.append(p("The following constants may be used:", st.bold))
    bullets = [ListItem(p(line, st.small), leftIndent=10) for line in lines]
    story.append(ListFlowable(bullets, bulletType="bullet", leftIndent=16))
    story.append(Spacer(1, 8))


def render_section_header(
    story: List[Any],
    st: Styles,
    section_letter: str,
    marks: Any,
    note: Optional[str] = None,
) -> None:
    marks_text = safe_text(marks)
    if marks_text:
        story.append(
            p(f"SECTION {section_letter} ({marks_text} Marks)", st.section_header)
        )
    else:
        story.append(p(f"SECTION {section_letter}", st.section_header))

    if note:
        story.append(p(note, st.center))
        story.append(Spacer(1, 4))


def render_section_a(
    story: List[Any], exam: Dict[str, Any], st: Styles, is_solution: bool
) -> None:
    section_a = exam.get("section_A", {})
    if not isinstance(section_a, dict) or not section_a:
        return

    mcq_marks = int(section_a.get("multiple_choice_marks") or 0)
    matching_marks = int(section_a.get("matching_marks") or 0)
    total_marks = mcq_marks + matching_marks
    marks = total_marks if total_marks > 0 else ""
    note = safe_text(section_a.get("section_instructions", ""))

    render_section_header(story, st, "A", marks, note or None)

    for fallback_idx, question in enumerate(
        sort_questions(section_a.get("question_list", [])), start=1
    ):
        question_type = detect_section_a_question_type(question)
        question_block: List[Any] = []
        if question_type == "multiple_choice":
            render_multiple_choice_question(
                question_block, question, st, is_solution, fallback_idx
            )
            append_question_block(
                story, question_block, spacer_height=8, keep_together=False
            )
        elif question_type == "item_matching":
            render_item_matching_question(
                question_block, question, st, is_solution, fallback_idx
            )
            append_question_block(story, question_block, spacer_height=8)
        else:
            question_number = extract_question_number(question, fallback_idx)
            prompt_text = safe_text(question.get("prompt", "")) or safe_text(
                question.get("question", "")
            )
            heading = section_a_heading_markup(
                question_number, prompt_text, question.get("marks")
            )
            question_block.append(p_markup(heading, st.base))
            append_question_block(story, question_block, spacer_height=8)


def render_multiple_choice_question(
    story: List[Any],
    question: Dict[str, Any],
    st: Styles,
    is_solution: bool,
    fallback_number: int,
) -> None:
    question_number = extract_question_number(question, fallback_number)
    prompt = safe_text(question.get("prompt", ""))
    heading = section_a_heading_markup(question_number, prompt, question.get("marks"))
    story.append(p_markup(heading, st.base))
    story.append(Spacer(1, 2))

    items = question.get("items", [])
    for idx, item in enumerate(items, start=1):
        item_block: List[Any] = []
        label = safe_text(item.get("label")) or roman_like_label(idx)
        item_text = safe_text(item.get("question", ""))
        item_block.append(p(f"({label}) {item_text}", st.part))

        options = normalize_mcq_options(item.get("options", []))
        if options:
            rows = []
            correct_label = safe_text(item.get("answer")).upper()
            for option_label, option_text in options:
                left = p(f"{option_label}.", st.part)
                if is_solution and option_label == correct_label:
                    right = p_markup(
                        f"<b>{escape(option_text)} <font color='red'>[CORRECT]</font></b>",
                        st.base,
                    )
                else:
                    right = p(option_text, st.base)
                rows.append([left, right])

            option_table = Table(rows, colWidths=[12 * mm, 148 * mm])
            option_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), "Times-Roman"),
                        ("FONTSIZE", (0, 0), (-1, -1), 11),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 1),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                    ]
                )
            )
            item_block.append(option_table)

        if is_solution and item.get("answer"):
            item_block.append(p(f"Answer: {item.get('answer')}", st.answer))

        append_question_block(story, item_block, spacer_height=2)


def render_item_matching_question(
    story: List[Any],
    question: Dict[str, Any],
    st: Styles,
    is_solution: bool,
    fallback_number: int,
) -> None:
    question_number = extract_question_number(question, fallback_number)
    prompt = safe_text(question.get("prompt", ""))
    heading = section_a_heading_markup(question_number, prompt, question.get("marks"))
    story.append(p_markup(heading, st.base))
    story.append(Spacer(1, 3))

    list_a = normalize_list_entries(question.get("listA", []), label_style="roman")
    list_b = normalize_list_entries(question.get("listB", []), label_style="alpha")
    row_count = max(1, len(list_a), len(list_b))

    rows: List[List[Any]] = [[p("List A", st.bold), p("List B", st.bold)]]
    for index in range(row_count):
        left = ""
        right = ""
        if index < len(list_a):
            left_label, left_text = list_a[index]
            left = f"({left_label}) {left_text}"
        if index < len(list_b):
            right_label, right_text = list_b[index]
            right = f"{right_label}. {right_text}"
        rows.append([p(left, st.base), p(right, st.base)])

    table = Table(rows, colWidths=[85 * mm, 85 * mm])
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)

    if is_solution:
        answers_pairs = question.get("answers_pairs", {})
        if isinstance(answers_pairs, dict) and answers_pairs:
            story.append(Spacer(1, 4))
            story.append(p("Suggested matching answers:", st.answer_heading))
            answer_rows: List[List[Any]] = [
                [p("List A Item", st.answer), p("Matching List B Item", st.answer)]
            ]
            for key, value in answers_pairs.items():
                answer_rows.append([p(key, st.answer), p(value, st.answer)])
            answer_table = Table(answer_rows, colWidths=[60 * mm, 110 * mm])
            answer_table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.darkred),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.append(answer_table)


def render_section_b(
    story: List[Any], exam: Dict[str, Any], st: Styles, is_solution: bool
) -> None:
    section_b = exam.get("section_B", {})
    if not isinstance(section_b, dict) or not section_b:
        return

    story.append(Spacer(1, 8))
    render_section_header(
        story,
        st,
        "B",
        section_b.get("marks", ""),
        safe_text(section_b.get("section_instructions", "")) or None,
    )

    questions = sort_questions(section_b.get("question_list", []))
    for fallback_idx, question in enumerate(questions, start=1):
        question_block: List[Any] = []
        render_short_answer_question(
            question_block, question, st, is_solution, fallback_idx
        )
        append_question_block(story, question_block, spacer_height=9)


def render_short_answer_question(
    story: List[Any],
    question: Dict[str, Any],
    st: Styles,
    is_solution: bool,
    fallback_number: int,
) -> None:
    question_number = extract_question_number(question, fallback_number)
    marks_text = safe_text(question.get("marks"))
    title = f"{question_number}."
    if marks_text:
        title = f"{title} ({marks_text} marks)"
    story.append(p(title, st.bold))

    for part in question.get("parts", []):
        part_label = safe_text(part.get("label", ""))
        part_prompt = safe_text(part.get("prompt", ""))
        sub_questions = part.get("sub_questions", [])
        has_sub_questions = isinstance(sub_questions, list) and bool(sub_questions)
        part_suffix = "" if has_sub_questions else marks_suffix(part.get("marks"))
        if part_prompt:
            story.append(p(f"({part_label}) {part_prompt}{part_suffix}", st.part))
        else:
            story.append(p(f"({part_label}){part_suffix}", st.part))

        for sub in sub_questions if isinstance(sub_questions, list) else []:
            sub_label = safe_text(sub.get("label", ""))
            sub_text = safe_text(sub.get("text", ""))
            sub_suffix = marks_suffix(sub.get("marks"))
            story.append(p(f"({sub_label}) {sub_text}{sub_suffix}", st.subpart))
            story.append(Spacer(1, 2))

    if is_solution:
        render_solution_block(story, question.get("answer"), st)


def render_section_c(
    story: List[Any], exam: Dict[str, Any], st: Styles, is_solution: bool
) -> None:
    section_c = exam.get("section_C", {})
    if not isinstance(section_c, dict) or not section_c:
        return

    story.append(Spacer(1, 8))
    render_section_header(
        story,
        st,
        "C",
        section_c.get("marks", ""),
        safe_text(section_c.get("section_instructions", "")) or None,
    )

    questions = sort_questions(section_c.get("question_list", []))
    for fallback_idx, question in enumerate(questions, start=1):
        question_block: List[Any] = []
        render_long_answer_question(
            question_block, question, st, is_solution, fallback_idx
        )
        append_question_block(story, question_block, spacer_height=9)


def render_long_answer_question(
    story: List[Any],
    question: Dict[str, Any],
    st: Styles,
    is_solution: bool,
    fallback_number: int,
) -> None:
    question_number = extract_question_number(question, fallback_number)
    marks_text = safe_text(question.get("marks"))
    heading = f"{question_number}."
    if marks_text:
        heading = f"{heading} ({marks_text} marks)"
    story.append(p(heading, st.bold))

    description = safe_text(question.get("description", ""))
    if description:
        story.append(p(description, st.base))

    task = question.get("task", {})
    if isinstance(task, dict):
        task_prompt = safe_text(task.get("prompt", ""))
        if task_prompt:
            story.append(p(task_prompt, st.part))

        for sub in task.get("sub_questions", []):
            sub_label = safe_text(sub.get("label", ""))
            sub_prompt = safe_text(sub.get("prompt", ""))
            sub_marks = safe_text(sub.get("marks", ""))
            suffix = f" ({sub_marks} marks)" if sub_marks else ""
            story.append(p(f"({sub_label}) {sub_prompt}{suffix}", st.subpart))

    if is_solution:
        render_solution_block(story, question.get("answer"), st)


def render_solution_block(story: List[Any], answer_payload: Any, st: Styles) -> None:
    if not answer_payload:
        return

    if isinstance(answer_payload, dict):
        example_answer = answer_payload.get("example_answer")
        marking_scheme = answer_payload.get("marking_scheme")
        marking_points = answer_payload.get("marking_points", [])

        if example_answer:
            story.append(p("Suggested answer:", st.answer_heading))
            for line in format_answer_lines(example_answer):
                story.append(p(line, st.answer))

        if marking_scheme:
            story.append(p("Marking scheme:", st.answer_heading))
            story.append(p(marking_scheme, st.answer))

        if isinstance(marking_points, list) and marking_points:
            story.append(p("Marking points:", st.answer_heading))
            bullets = [
                ListItem(p(point, st.answer), leftIndent=10) for point in marking_points
            ]
            story.append(ListFlowable(bullets, bulletType="bullet", leftIndent=20))
    else:
        story.append(p("Suggested answer:", st.answer_heading))
        for line in format_answer_lines(answer_payload):
            story.append(p(line, st.answer))


def page_number_footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont("Times-Roman", 10)
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_story(exam: Dict[str, Any], st: Styles, is_solution: bool) -> List[Any]:
    story: List[Any] = []
    render_header(story, exam, st, is_solution)
    render_instructions(story, exam, st)
    render_constants(story, exam, st)
    render_section_a(story, exam, st, is_solution)
    render_section_b(story, exam, st, is_solution)
    render_section_c(story, exam, st, is_solution)
    return story


def build_pdf(
    exam: Dict[str, Any], out_path: str | Path, is_solution: bool = False
) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    st = build_styles()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=safe_text(exam.get("meta", {}).get("subject", "Exam")),
        author="Twiga-Generated",
    )
    story = build_story(exam, st, is_solution)
    doc.build(story, onFirstPage=page_number_footer, onLaterPages=page_number_footer)


def build_exam_pdf(exam: Dict[str, Any], out_path: str | Path) -> None:
    build_pdf(exam, out_path, is_solution=False)


def build_solution_pdf(exam: Dict[str, Any], out_path: str | Path) -> None:
    build_pdf(exam, out_path, is_solution=True)


def load_exam_json(json_path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(json_path).read_text(encoding="utf-8"))


def _resolve_dev_json_path() -> Path:
    output_dir = Path(__file__).parent / "output_tool"
    candidates = [output_dir / "exam_text9.json", output_dir / "exam_test9.json"]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        "Could not find development exam JSON. Expected one of: "
        + ", ".join(str(path) for path in candidates)
    )


def main() -> None:
    exam_json_path = _resolve_dev_json_path()
    exam = load_exam_json(exam_json_path)

    output_dir = Path(__file__).parent / "output_tool"
    stem = exam_json_path.stem
    exam_pdf_path = output_dir / f"{stem}.pdf"
    solution_pdf_path = output_dir / f"{stem}_solution.pdf"

    build_exam_pdf(exam, exam_pdf_path)
    build_solution_pdf(exam, solution_pdf_path)

    print(f"Exam PDF saved to: {exam_pdf_path}")
    print(f"Solution PDF saved to: {solution_pdf_path}")


if __name__ == "__main__":
    main()
