import asyncio
import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# `app.__init__` imports colorlog for logger setup; keep this test runnable
# in lean environments where optional logging deps are not installed.
if "colorlog" not in sys.modules:
    colorlog_module = types.ModuleType("colorlog")

    class _DummyColoredFormatter:  # pragma: no cover - simple import shim
        def __init__(self, *args, **kwargs) -> None:
            pass

    colorlog_module.ColoredFormatter = _DummyColoredFormatter
    sys.modules["colorlog"] = colorlog_module

if "app.utils.llm_utils" not in sys.modules:
    llm_utils_module = types.ModuleType("app.utils.llm_utils")

    async def _placeholder_async_llm_request(*args, **kwargs):  # pragma: no cover
        raise RuntimeError("async_llm_request should be patched in tests.")

    llm_utils_module.async_llm_request = _placeholder_async_llm_request
    sys.modules["app.utils.llm_utils"] = llm_utils_module

from app.tools.tool_code.generate_necta_style_exam.exam_generator import (
    ExamGenerator,
    QuestionType,
)


def test_generate_single_item_matching_sets_question_type() -> None:
    generator = ExamGenerator()
    llm_payload = {
        "prompt": "Match items in List A with List B.",
        "listA": [{"label": "i", "text": "Acid"}],
        "listB": [{"label": "A", "text": "Turns blue litmus red"}],
        "answers_pairs": {"i": "A"},
        "allow_reuse_listB": True,
        "metadata": {"topic": "Acids and bases", "difficulty": "medium"},
    }

    with patch(
        "app.tools.tool_code.generate_necta_style_exam.exam_generator.async_llm_request",
        AsyncMock(return_value=SimpleNamespace(content=json.dumps(llm_payload))),
    ):
        success, question = asyncio.run(
            generator._generate_single_question(
                question_type=QuestionType.ITEM_MATCHING,
                subject="Chemistry",
                topic="Acids and bases",
                chunk_list=[{"id": 123, "content": "Acids turn blue litmus red."}],
                previous_questions=[],
                template=generator.matching_template,
                question_id="A-Q2",
                num_marks=5,
                difficulty="medium",
            )
        )

    assert success is True
    assert list(question.keys())[:3] == ["id", "type", "marks"]
    assert question["type"] == QuestionType.ITEM_MATCHING.value
    assert question["id"] == "A-Q2"
    assert question["marks"] == 5
