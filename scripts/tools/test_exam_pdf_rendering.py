"""
Manual test script for exam PDF rendering (use this for development to avoid running the full generation pipeline).

This script loads an exam JSON file and renders:
- Exam PDF
- Solution PDF

Usage:
    python scripts/tools/test_exam_pdf_rendering.py
    python scripts/tools/test_exam_pdf_rendering.py --input scripts/tools/data/example_exam.json
    python scripts/tools/test_exam_pdf_rendering.py --output-dir scripts/tools/outputs

Docker usage:
    docker-compose -f docker/dev/docker-compose.yml --env-file .env run --rm app bash -c "PYTHONPATH=/app uv run python scripts/tools/test_exam_pdf_rendering.py --input scripts/tools/data/example_exam_math.json"
    docker-compose -f docker/dev/docker-compose.yml --env-file .env run --rm app bash -c "PYTHONPATH=/app uv run python scripts/tools/test_exam_pdf_rendering.py --input scripts/tools/data/example_exam.json"
"""

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.exam_pdf_generation_service import (
    ExamRenderType,
    backend_for_subject,
    render_exam_pdf,
    render_exam_solution_pdf,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render exam and solution PDFs from JSON."
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Path to exam JSON input file. Defaults to scripts/tools/data/example_exam_math.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory for generated PDFs. Defaults to scripts/tools/outputs.",
    )
    return parser.parse_args()


def load_exam_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    script_dir = Path(__file__).resolve().parent
    input_path = args.input or (script_dir / "data" / "example_exam_math.json")
    output_dir = args.output_dir or (script_dir / "outputs")
    return input_path, output_dir


def main() -> None:
    args = parse_args()
    input_path, output_dir = resolve_paths(args)
    if not input_path.exists():
        raise FileNotFoundError(f"Could not find input JSON at: {input_path}")
    output_dir.mkdir(parents=True, exist_ok=True)

    exam_json = load_exam_json(input_path)
    stem = input_path.stem

    exam_pdf_path = output_dir / f"{stem}.pdf"
    solution_pdf_path = output_dir / f"{stem}_solution.pdf"

    meta = exam_json.get("meta", {}) if isinstance(exam_json, dict) else {}
    subject = meta.get("subject") if isinstance(meta, dict) else None
    subject_for_rendering = subject if isinstance(subject, str) else None
    selected_backend = backend_for_subject(subject_for_rendering)
    print(
        "Detected rendering mode by subject: "
        + (
            "LaTeX backend (with ReportLab fallback)"
            if selected_backend == ExamRenderType.LATEX
            else "ReportLab backend"
        )
    )

    render_exam_pdf(
        exam_json,
        exam_pdf_path,
        subject=subject_for_rendering,
    )
    render_exam_solution_pdf(
        exam_json,
        solution_pdf_path,
        subject=subject_for_rendering,
    )

    if not exam_pdf_path.exists():
        raise RuntimeError(f"Exam PDF was not created: {exam_pdf_path}")
    if not solution_pdf_path.exists():
        raise RuntimeError(f"Solution PDF was not created: {solution_pdf_path}")

    print(f"Exam PDF saved to: {exam_pdf_path.resolve()}")
    print(f"Solution PDF saved to: {solution_pdf_path.resolve()}")


if __name__ == "__main__":
    main()
