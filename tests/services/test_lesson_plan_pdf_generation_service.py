from unittest.mock import patch

from app.services.lesson_plan_pdf_generation_service import (
    build_lesson_plan_latex_body,
    render_lesson_plan_pdf,
)
from app.tools.tool_code.create_lesson_plan.main import format_lesson_plan_as_text

SAMPLE_LESSON_PLAN = {
    "lesson_title": "Introduction to Algebra",
    "subject": "Mathematics",
    "topic": "Equations",
    "duration_minutes": 45,
    "learning_objectives": [
        "Solve linear equations",
        "Explain the balance method",
    ],
    "key_concepts": ["Balance method", "Inverse operations"],
    "materials_preparation": {
        "materials_needed": ["Whiteboard", "Markers"],
        "teacher_preparation": ["Prepare worked examples"],
    },
    "lesson_flow": [
        {
            "title": "Introduction",
            "duration_minutes": 10,
            "activities": [
                {"type": "instruction", "content": "Review prior knowledge"},
                {
                    "type": "exercise",
                    "prompt": "Solve $x + 2 = 5$",
                    "answer": "$x = 3$",
                },
            ],
        },
        {
            "title": "Practice",
            "duration_minutes": 20,
            "activities": ["Work through example 2"],
        },
    ],
    "homework": ["Complete exercise set A"],
}


def test_build_lesson_plan_latex_body_uses_headings_and_lists() -> None:
    latex = build_lesson_plan_latex_body(SAMPLE_LESSON_PLAN)

    assert r"\section*{Introduction to Algebra}" in latex
    assert r"\textbf{Subject:} Mathematics" in latex
    assert r"\textbf{Topic:} Equations" in latex
    assert r"\textbf{Duration:} 45 minutes" in latex
    assert r"\subsection*{Learning Objectives}" in latex
    assert r"\begin{enumerate}" in latex
    assert r"\item Solve linear equations" in latex
    assert r"\subsection*{Key Concepts}" in latex
    assert r"\begin{itemize}" in latex
    assert r"\item Balance method" in latex
    assert r"\subsection*{Materials \& Preparation}" in latex
    assert r"\subsubsection*{Materials needed}" in latex
    assert r"\subsubsection*{Teacher preparation}" in latex
    assert r"\subsection*{Lesson Flow}" in latex
    assert r"\subsubsection*{Introduction (10 min)}" in latex
    assert r"\item Review prior knowledge" in latex
    assert r"\item \textbf{Exercise:} Solve $x + 2 = 5$" in latex
    assert r"\item \textit{Answer:} $x = 3$" in latex
    assert r"\subsubsection*{Practice (20 min)}" in latex
    assert r"\item Work through example 2" in latex
    assert r"\subsection*{Homework}" in latex
    assert r"\item Complete exercise set A" in latex


def test_build_lesson_plan_latex_body_escapes_special_chars_and_keeps_math() -> None:
    plan = {
        "lesson_title": "Rates & Ratios",
        "subject": "Mathematics",
        "topic": "Percentages",
        "duration_minutes": 40,
        "learning_objectives": ["Use $a^2 + b^2 = c^2$ and 50% growth"],
        "key_concepts": ["cost & benefit"],
    }

    latex = build_lesson_plan_latex_body(plan)

    assert r"\section*{Rates \& Ratios}" in latex
    assert r"\textbf{Subject:} Mathematics" in latex
    assert r"$a^2 + b^2 = c^2$" in latex
    assert r"50\% growth" in latex
    assert r"cost \& benefit" in latex


def test_format_lesson_plan_as_text_keeps_readable_fallback() -> None:
    text = format_lesson_plan_as_text(SAMPLE_LESSON_PLAN)

    assert "Lesson Plan: Introduction to Algebra" in text
    assert "Learning Objectives:" in text
    assert "1. Solve linear equations" in text
    assert "- Balance method" in text
    assert "Exercise: Solve $x + 2 = 5$" in text
    assert "Answer: $x = 3$" in text


def test_render_lesson_plan_pdf_copies_compiled_output(tmp_path) -> None:
    compiled_pdf = tmp_path / "compiled.pdf"
    compiled_pdf.write_bytes(b"%PDF-1.4")
    output_path = tmp_path / "lesson_plan.pdf"

    with patch(
        "app.services.lesson_plan_pdf_generation_service.compile_latex_to_pdf",
        return_value=str(compiled_pdf),
    ) as mock_compile:
        render_lesson_plan_pdf(SAMPLE_LESSON_PLAN, output_path)

    mock_compile.assert_called_once()
    latex_body = mock_compile.call_args.args[0]
    assert r"\section*{Introduction to Algebra}" in latex_body
    assert output_path.exists()
    assert output_path.read_bytes() == b"%PDF-1.4"
