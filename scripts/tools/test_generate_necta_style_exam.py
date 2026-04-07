"""
Manual test script for the generate_necta_style_exam function.
This script saves the generated exam JSON to disk.

This script tests the actual generate_necta_style_exam function that uses an LLM.
Run this manually to verify the function works correctly, but it should NOT
be run in automated test suites due to cost and external dependencies.

Usage:
    docker-compose -f docker/dev/docker-compose.yml --env-file .env run --rm app bash -c "PYTHONPATH=/app uv run python scripts/tools/test_generate_necta_style_exam.py"
"""

import asyncio
import json
from pathlib import Path

from app.database.db import get_exam
from app.tools.tool_code.generate_necta_style_exam.main import generate_necta_style_exam


async def main():
    print("Starting generation test...")

    class_id = 1
    user_id = 1
    subject = "Chemistry"
    topics = ["Atomic Structure", "Periodic Table", "Chemical Bonding"]

    result = await generate_necta_style_exam(
        class_id=class_id, subject=subject, topics=topics, user_id=user_id
    )
    print(f"Tool response: {result}")

    response_payload = json.loads(result)
    exam_id = response_payload.get("exam_id")
    if not exam_id:
        raise RuntimeError("No exam_id returned from generate_necta_style_exam.")

    exam_record = await get_exam(exam_id)
    if exam_record is None:
        raise RuntimeError(f"Generated exam with exam_id={exam_id} not found in DB.")

    output_dir = Path(__file__).resolve().parent / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_subject = subject.strip().lower().replace(" ", "_")
    output_path = output_dir / f"{safe_subject}_{exam_id}.json"
    output_path.write_text(
        json.dumps(exam_record.exam_json, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Saved generated exam JSON to: {output_path.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
