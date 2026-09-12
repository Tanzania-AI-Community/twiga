from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.latex.latex_artifact_generator import compile_latex_to_pdf
from app.services.exam_rendering.latex_exam_pdf_rendering import normalize_inline_text


def build_lesson_plan_latex_body(plan: dict[str, Any]) -> str:
    lines: list[str] = []

    title = normalize_inline_text(plan.get("lesson_title", "Lesson Plan"))
    lines.append(rf"\section*{{{title}}}")
    lines.append("")

    metadata_parts: list[str] = []
    subject = normalize_inline_text(plan.get("subject", ""))
    topic = normalize_inline_text(plan.get("topic", ""))
    duration = plan.get("duration_minutes", 45)
    if subject:
        metadata_parts.append(rf"\textbf{{Subject:}} {subject}")
    if topic:
        metadata_parts.append(rf"\textbf{{Topic:}} {topic}")
    metadata_parts.append(
        rf"\textbf{{Duration:}} {normalize_inline_text(duration)} minutes"
    )
    lines.append(r"\noindent " + r" \\ ".join(metadata_parts))
    lines.append("")

    objectives = plan.get("learning_objectives", [])
    if isinstance(objectives, list) and objectives:
        lines.append(r"\subsection*{Learning Objectives}")
        lines.append(r"Students will be able to:")
        lines.extend(_enumerate_items(objectives))
        lines.append("")

    key_concepts = plan.get("key_concepts", [])
    if isinstance(key_concepts, list) and key_concepts:
        lines.append(r"\subsection*{Key Concepts}")
        lines.extend(_itemize_items(key_concepts))
        lines.append("")

    materials = plan.get("materials_preparation", {})
    if isinstance(materials, dict):
        materials_needed = materials.get("materials_needed", [])
        teacher_prep = materials.get("teacher_preparation", [])
        if (isinstance(materials_needed, list) and materials_needed) or (
            isinstance(teacher_prep, list) and teacher_prep
        ):
            lines.append(r"\subsection*{Materials \& Preparation}")
            if isinstance(materials_needed, list) and materials_needed:
                lines.append(r"\subsubsection*{Materials needed}")
                lines.extend(_itemize_items(materials_needed))
            if isinstance(teacher_prep, list) and teacher_prep:
                lines.append(r"\subsubsection*{Teacher preparation}")
                lines.extend(_itemize_items(teacher_prep))
            lines.append("")

    lesson_flow = plan.get("lesson_flow", [])
    if isinstance(lesson_flow, list) and lesson_flow:
        lines.append(r"\subsection*{Lesson Flow}")
        for section in lesson_flow:
            if not isinstance(section, dict):
                continue
            section_title = normalize_inline_text(section.get("title", "Section"))
            duration_minutes = section.get("duration_minutes", "")
            heading = section_title
            if duration_minutes != "" and duration_minutes is not None:
                heading = (
                    f"{section_title} "
                    f"({normalize_inline_text(duration_minutes)} min)"
                )
            lines.append(rf"\subsubsection*{{{heading}}}")
            lines.extend(_build_activity_list(section.get("activities", [])))
            lines.append("")

    homework = plan.get("homework", [])
    if isinstance(homework, list) and homework:
        lines.append(r"\subsection*{Homework}")
        lines.extend(_itemize_items(homework))
        lines.append("")

    return "\n".join(line for line in lines if line is not None).strip() + "\n"


def render_lesson_plan_pdf(plan: dict[str, Any], output_path: str | Path) -> None:
    latex_body = build_lesson_plan_latex_body(plan)
    if not latex_body.strip():
        raise ValueError("Lesson plan produced an empty LaTeX body.")

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="twiga-lesson-plan-pdf-") as temp_dir:
        compiled_pdf = compile_latex_to_pdf(latex_body, temp_dir)
        shutil.copyfile(compiled_pdf, destination)


def _itemize_items(items: list[Any]) -> list[str]:
    lines = [r"\begin{itemize}"]
    for item in items:
        text = normalize_inline_text(item)
        if text:
            lines.append(rf"  \item {text}")
    lines.append(r"\end{itemize}")
    return lines if len(lines) > 2 else []


def _enumerate_items(items: list[Any]) -> list[str]:
    lines = [r"\begin{enumerate}"]
    for item in items:
        text = normalize_inline_text(item)
        if text:
            lines.append(rf"  \item {text}")
    lines.append(r"\end{enumerate}")
    return lines if len(lines) > 2 else []


def _build_activity_list(activities: Any) -> list[str]:
    if not isinstance(activities, list) or not activities:
        return []

    lines = [r"\begin{itemize}"]
    for activity in activities:
        if isinstance(activity, str):
            text = normalize_inline_text(activity)
            if text:
                lines.append(rf"  \item {text}")
            continue

        if not isinstance(activity, dict):
            continue

        activity_type = str(activity.get("type") or "").strip().lower()
        if activity_type == "exercise":
            prompt = normalize_inline_text(activity.get("prompt", ""))
            answer = normalize_inline_text(activity.get("answer", ""))
            if prompt:
                lines.append(rf"  \item \textbf{{Exercise:}} {prompt}")
            if answer:
                lines.append(rf"  \item \textit{{Answer:}} {answer}")
            continue

        content = activity.get("content") or activity.get("prompt")
        text = normalize_inline_text(content)
        if text:
            lines.append(rf"  \item {text}")

    lines.append(r"\end{itemize}")
    return lines if len(lines) > 2 else []
