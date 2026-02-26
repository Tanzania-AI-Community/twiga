from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    ListFlowable,
    ListItem,
    HRFlowable,
)

# ----------------------------
# Text + formatting helpers
# ----------------------------

def safe_text(value: Any) -> str:
    """Convert to string and normalize whitespace."""
    if value is None:
        return ""
    s = str(value)
    s = s.replace("\u2011", "-")  # non-breaking hyphen -> normal hyphen
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def p(text: str, style: ParagraphStyle) -> Paragraph:
    """Create a reportlab Paragraph with normalized text."""
    return Paragraph(safe_text(text), style)


def roman_like_label(i: int) -> str:
    """For MCQ items: (i) ... (x) fallback to numeric."""
    labels = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
    return labels[i - 1] if 1 <= i <= len(labels) else str(i)


# ----------------------------
# Styles
# ----------------------------

@dataclass(frozen=True)
class Styles:
    base: ParagraphStyle
    title: ParagraphStyle
    center: ParagraphStyle
    bold: ParagraphStyle
    section_header: ParagraphStyle
    small: ParagraphStyle


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
        alignment=1,  # centered
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

    return Styles(
        base=base,
        title=title,
        center=center,
        bold=bold,
        section_header=section_header,
        small=small,
    )


# ----------------------------
# Rendering blocks
# ----------------------------

def render_header(story: List[Any], exam: Dict[str, Any], st: Styles) -> None:
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
    subject = safe_text(meta.get("subject", ""))
    duration = safe_text(meta.get("duration", ""))
    year = safe_text(meta.get("year", ""))

    if exam_title:
        story.append(p(exam_title, st.title))
    if subject:
        story.append(p(subject, st.title))

    time_year_tbl = Table(
        [[f"Time: {duration}", f"YEAR: {year}"]],
        colWidths=[80 * mm, 80 * mm],
    )
    time_year_tbl.setStyle(
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
    story.append(time_year_tbl)
    horizontal_line = HRFlowable(width="100%", thickness=1, color=colors.black, spaceBefore=0, spaceAfter=0)
    story.append(horizontal_line)
    story.append(Spacer(1, 6))


def render_instructions(story: List[Any], exam: Dict[str, Any], st: Styles) -> None:
    instructions = exam.get("instructions", [])
    story.append(p("<b>INSTRUCTIONS</b>", st.center))
    for idx, line in enumerate(instructions, start=1):
        story.append(p(f"{idx}. {line}", st.center))
    story.append(Spacer(1, 6))


def render_constants(story: List[Any], exam: Dict[str, Any], st: Styles) -> None:
    constants = exam.get("constants", {})

    story.append(p("The following constants may be used:", st.bold))

    atomic_masses = constants.get("atomic_masses", {})
    lines: List[str] = []

    if isinstance(atomic_masses, dict) and atomic_masses:
        pairs = [f"{k} = {atomic_masses[k]}" for k in atomic_masses.keys()]
        lines.append("Atomic masses: " + ", ".join(pairs))

    mapping = [
        ("avogadro", "Avogadro’s number"),
        ("gmv_stp", "GMV at s.t.p"),
        ("faraday", "1 Faraday"),
        ("std_temp", "Standard temperature"),
        ("litre_equiv", ""),
    ]

    for key, label in mapping:
        val = constants.get(key)
        if not val:
            continue
        if key == "litre_equiv":
            lines.append(str(val))
        else:
            lines.append(f"{label} = {val}")

    bullets = [ListItem(p(x, st.small), leftIndent=10) for x in lines]
    story.append(ListFlowable(bullets, bulletType="bullet", leftIndent=16))
    story.append(Spacer(1, 8))


def render_section_header(
    story: List[Any],
    st: Styles,
    section_letter: str,
    marks: Any,
    note: Optional[str] = None,
) -> None:
    story.append(p(f"SECTION {section_letter} ({marks} Marks)", st.section_header))
    if note:
        story.append(p(note, st.center))
        story.append(Spacer(1, 4))


def render_section_a(story: List[Any], exam: Dict[str, Any], st: Styles) -> None:
    secA = exam.get("sections", {}).get("A", {})
    if not secA:
        return

    render_section_header(
        story, st, "A", secA.get("marks", ""), "Answer all questions in this section"
    )

    render_mcq_q1(story, secA, st)
    story.append(Spacer(1, 6))
    render_matching_q2(story, secA, st)


def render_mcq_q1(story: List[Any], secA: Dict[str, Any], st: Styles) -> None:
    q1 = secA.get("q1_mcq", {})
    if not q1:
        return

    story.append(p("1. " + safe_text(q1.get("stem", "")), st.base))

    items = q1.get("items", [])
    for i, item in enumerate(items, start=1):
        label = safe_text(item.get("label")) or roman_like_label(i)
        qtext = safe_text(item.get("question", ""))

        story.append(Spacer(1, 2))
        story.append(p(f"({label}) {qtext}", st.base))

        opts = item.get("options", {})
        opt_rows = []
        for letter in ["A", "B", "C", "D", "E"]:
            if letter in opts:
                opt_rows.append([f"{letter}.", safe_text(opts[letter])])

        opt_tbl = Table(opt_rows, colWidths=[10 * mm, 160 * mm])
        opt_tbl.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Times-Roman"),
                    ("FONTSIZE", (0, 0), (-1, -1), 11),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            )
        )
        story.append(opt_tbl)


def render_matching_q2(story: List[Any], secA: Dict[str, Any], st: Styles) -> None:
    q2 = secA.get("q2_matching", {})
    if not q2:
        return

    story.append(p("2. " + safe_text(q2.get("prompt", "")), st.base))
    story.append(Spacer(1, 4))

    listA = q2.get("listA", [])
    listB = q2.get("listB", [])

    left_lines = [f"({a.get('label','')}) {a.get('text','')}" for a in listA]
    right_lines = [f"{b.get('label','')}. {b.get('text','')}" for b in listB]

    n = max(len(left_lines), len(right_lines), 1)
    rows = [["List A", "List B"]]
    for r in range(n):
        la = safe_text(left_lines[r]) if r < len(left_lines) else ""
        lb = safe_text(right_lines[r]) if r < len(right_lines) else ""
        rows.append([la, lb])

    match_tbl = Table(rows, colWidths=[85 * mm, 85 * mm])
    match_tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(match_tbl)


def render_section_b(story: List[Any], exam: Dict[str, Any], st: Styles) -> None:
    secB = exam.get("sections", {}).get("B", {})
    if not secB:
        return

    story.append(Spacer(1, 10))
    render_section_header(
        story, st, "B", secB.get("marks", ""), "Answer all questions in this section"
    )

    for q in secB.get("questions", []):
        render_structured_question(story, q, st)


def render_structured_question(story: List[Any], q: Dict[str, Any], st: Styles) -> None:
    qno = q.get("number", "")
    story.append(p(f"{qno}.", st.bold))

    for part in q.get("parts", []):
        render_question_part(story, part, st)

    story.append(Spacer(1, 2))


def render_question_part(story: List[Any], part: Dict[str, Any], st: Styles) -> None:
    plabel = safe_text(part.get("label", ""))
    pprompt = safe_text(part.get("prompt", ""))
    ptype = safe_text(part.get("type", "short_answer"))

    if pprompt:
        story.append(p(f"({plabel}) {pprompt}", st.base))
    else:
        story.append(p(f"({plabel})", st.base))

    if ptype == "table_question" and part.get("table"):
        render_embedded_table(story, part["table"])

    for sp in part.get("subparts", []):
        splabel = safe_text(sp.get("label", ""))
        sptext = safe_text(sp.get("text", ""))
        story.append(p(f"({splabel}) {sptext}", st.base))

    story.append(Spacer(1, 4))


def render_embedded_table(story: List[Any], table_spec: Dict[str, Any]) -> None:
    headers = table_spec.get("headers", [])
    rows = table_spec.get("rows", [])
    data: List[List[str]] = []

    if headers:
        data.append([safe_text(h) for h in headers])
    for row in rows:
        data.append([safe_text(x) for x in row])

    tbl = Table(data, hAlign="LEFT")
    tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
                ("FONTSIZE", (0, 0), (-1, -1), 10.5),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(Spacer(1, 3))
    story.append(tbl)
    story.append(Spacer(1, 3))


def render_section_c(story: List[Any], exam: Dict[str, Any], st: Styles) -> None:
    secC = exam.get("sections", {}).get("C", {})
    if not secC:
        return

    story.append(Spacer(1, 8))
    render_section_header(
        story, st, "C", secC.get("marks", ""), safe_text(secC.get("rule", ""))
    )

    for q in secC.get("questions", []):
        qno = safe_text(q.get("number", ""))
        prompt = safe_text(q.get("prompt", ""))
        story.append(p(f"{qno}. {prompt}", st.base))
        story.append(Spacer(1, 6))


def page_number_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Times-Roman", 10)
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


# ----------------------------
# Public API
# ----------------------------

def build_story(exam: Dict[str, Any], st: Styles) -> List[Any]:
    story: List[Any] = []

    render_header(story, exam, st)
    render_instructions(story, exam, st)
    render_constants(story, exam, st)

    render_section_a(story, exam, st)
    render_section_b(story, exam, st)
    render_section_c(story, exam, st)

    return story


def build_pdf(exam: Dict[str, Any], out_path: str) -> None:
    st = build_styles()

    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=safe_text(exam.get("meta", {}).get("subject", "Exam")),
        author="Auto-generated",
    )

    story = build_story(exam, st)
    doc.build(story, onFirstPage=page_number_footer, onLaterPages=page_number_footer)


def load_exam_json(json_path: str) -> Dict[str, Any]:
    return json.loads(Path(json_path).read_text(encoding="utf-8"))


# ----------------------------
# CLI
# ----------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate NECTA-style exam PDF from JSON.")
    parser.add_argument("json_path", help="Path to exam JSON file")
    parser.add_argument("-o", "--output", default="exam.pdf", help="Output PDF filename")
    args = parser.parse_args()

    exam = load_exam_json(args.json_path)
    build_pdf(exam, args.output)
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
