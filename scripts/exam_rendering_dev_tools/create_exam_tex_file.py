"""
docker-compose -f docker/dev/docker-compose.yml --env-file .env run --rm app bash -c "PYTHONPATH=/app uv run python scripts/exam_rendering_dev_tools/create_exam_tex_file.py"
"""

import json
from pathlib import Path

from app.services.exam_rendering.latex_exam_pdf_rendering import build_exam_document

BASE_DIR = Path(__file__).resolve().parent
INPUT_PATH = BASE_DIR / "data" / "example_exam_chemistry.json"
OUTPUT_PATH = BASE_DIR / "outputs" / "generated_exam_chemistry.tex"


def main() -> None:
    """Generate `generated_exam_chemistry.tex` from `example_exam_chemistry.json`.

    Reads the hardcoded input path, builds LaTeX using the builder functions,
    writes the output file, and prints the generated path.
    """
    data = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    tex = build_exam_document(data)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(tex, encoding="utf-8")
    print(f"Generated: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
