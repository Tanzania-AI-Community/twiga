"""
Manual test script for the generate_necta_style_exam function.

This script tests the actual generate_necta_style_exam function that uses an LLM.
Run this manually to verify the function works correctly, but it should NOT
be run in automated test suites due to cost and external dependencies.

Usage:
    docker-compose -f docker/dev/docker-compose.yml --env-file .env run --rm app bash -c "PYTHONPATH=/app uv run python scripts/tools/test_generate_necta_style_exam.py"
"""

import asyncio
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

    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
