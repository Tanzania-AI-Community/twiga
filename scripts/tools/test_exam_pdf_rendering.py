"""
Manual test script for exam PDF rendering (use this for development to avoid running the full generation pipeline).

This script loads scripts/tools/data/example_exam.json and renders:
- Exam PDF
- Solution PDF

Usage:
    docker-compose -f docker/dev/docker-compose.yml --env-file .env run --rm app bash -c "PYTHONPATH=/app uv run python scripts/tools/test_exam_pdf_rendering.py"
"""

import json
from pathlib import Path

from app.services.exam_pdf_generation_service import build_exam_pdf, build_solution_pdf


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    input_path = script_dir / "data" / "example_exam.json"
    output_dir = script_dir / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise FileNotFoundError(f"Could not find input JSON at: {input_path}")

    exam_json = json.loads(input_path.read_text(encoding="utf-8"))
    stem = input_path.stem

    exam_pdf_path = output_dir / f"{stem}.pdf"
    solution_pdf_path = output_dir / f"{stem}_solution.pdf"

    build_exam_pdf(exam_json, exam_pdf_path)
    build_solution_pdf(exam_json, solution_pdf_path)

    print(f"Exam PDF saved to: {exam_pdf_path}")
    print(f"Solution PDF saved to: {solution_pdf_path}")


if __name__ == "__main__":
    main()
