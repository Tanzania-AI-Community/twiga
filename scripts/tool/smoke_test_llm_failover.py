"""Opt-in live Together smoke checks. Uses API credits; never sends WhatsApp messages.

Run from the repository root:
    PYTHONPATH=. python scripts/tool/smoke_test_llm_failover.py --output /tmp/llm-smoke.json

This checks connectivity and basic interface compatibility, not textbook quality.
"""

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from openai import NotFoundError

from app.config import LLMProvider, llm_settings
from app.tools.tool_code.create_lesson_plan.main import _parse_json_response
from app.tools.tool_code.generate_necta_style_exam.exam_generator import ExamGenerator
from app.utils import llm_utils
from app.utils.llm_failover import TogetherModelRouter

TOOL = {
    "type": "function",
    "function": {
        "name": "search_knowledge",
        "description": "Look up textbook information for the requested topic.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}


async def main(output: Path) -> int:
    models = list(
        dict.fromkeys([llm_settings.llm_name, *llm_settings.together_fallback_models])
    )
    original_pool = llm_settings.together_fallback_models
    data = {"started_utc": datetime.now(timezone.utc).isoformat(), "models": {}}

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    async def request(model, messages, **kwargs):
        return await llm_utils.async_llm_request(
            messages,
            model_name=model,
            provider=LLMProvider.TOGETHER,
            api_key=llm_settings.api_key,
            max_tokens=4096,
            **kwargs,
        )

    try:
        # A model's capability check must not silently be answered by a fallback.
        llm_settings.together_fallback_models = []
        for model in models:
            results = data["models"][model] = {}
            cases = {
                "chat": [
                    HumanMessage(
                        content="Greet a secondary-school teacher in one short English sentence."
                    )
                ],
                "json": [
                    SystemMessage(
                        content='Return only a JSON object with keys "question" and "answer", both strings. Use only this source: evaporation changes liquid water into water vapour.'
                    ),
                    HumanMessage(
                        content="Create one short question and its correct answer from the source."
                    ),
                ],
                "equation": [
                    HumanMessage(
                        content="Solve (x^2-4)/(x-2)=4. Check the domain. Return a short explanation and final answer in English."
                    )
                ],
                "tool_call": [
                    SystemMessage(
                        content="Call search_knowledge before answering any textbook question."
                    ),
                    HumanMessage(content="Explain evaporation from the textbook."),
                ],
            }
            for name, messages in cases.items():
                started = time.monotonic()
                reply = None
                raw_json_valid = None
                try:
                    kwargs = (
                        {"tools": [TOOL], "tool_choice": "auto"}
                        if name == "tool_call"
                        else {}
                    )
                    reply = await request(model, messages, **kwargs)
                    checks = {
                        "completed": True,
                        "not_truncated": reply.response_metadata.get("finish_reason")
                        != "length",
                    }
                    if name == "json":
                        try:
                            json.loads(reply.content)
                            raw_json_valid = True
                        except (ValueError, TypeError):
                            raw_json_valid = False
                        parsed = _parse_json_response(reply.content)
                        exam_parsed = ExamGenerator()._parse_json_response(
                            reply.content
                        )
                        checks["json_fields"] = isinstance(parsed, dict) and all(
                            isinstance(parsed.get(k), str)
                            for k in ["question", "answer"]
                        )
                        checks["both_twiga_parsers"] = parsed == exam_parsed
                    elif name == "tool_call":
                        calls = reply.tool_calls
                        checks["native_call"] = bool(calls) and all(
                            call["name"] == "search_knowledge"
                            and isinstance(call["args"].get("query"), str)
                            for call in calls
                        )
                        if checks["native_call"]:
                            followup = await request(
                                model,
                                [
                                    *messages,
                                    reply,
                                    *[
                                        ToolMessage(
                                            content="Evaporation is the change of liquid water into water vapour.",
                                            tool_call_id=call["id"],
                                        )
                                        for call in calls
                                    ],
                                ],
                                tools=[TOOL],
                                tool_choice="none",
                            )
                            checks["tool_result_consumed"] = (
                                bool(followup.content) and not followup.tool_calls
                            )
                            results["tool_followup"] = {
                                "content": followup.content,
                                "tool_calls": followup.tool_calls,
                                "model": followup.response_metadata.get("model_name"),
                            }
                    else:
                        checks["nonempty_text"] = bool(reply.content)
                    results[name] = {
                        "checks": checks,
                        "content": reply.content,
                        "tool_calls": reply.tool_calls,
                        "model": reply.response_metadata.get("model_name"),
                        "usage": reply.usage_metadata,
                    }
                    if raw_json_valid is not None:
                        results[name]["raw_json_valid"] = raw_json_valid
                except Exception as error:
                    # Error bodies may contain request content; only save type/status.
                    results[name] = {
                        "checks": {"completed": False},
                        "error_type": type(error).__name__,
                        "status": getattr(error, "status_code", None),
                        "content": reply.content if reply is not None else None,
                    }
                results[name]["seconds"] = round(time.monotonic() - started, 3)
                save()
                print(
                    json.dumps(
                        {
                            "model": model,
                            "case": name,
                            **results[name].get("checks", {}),
                        }
                    ),
                    flush=True,
                )

        # Exercise the actual request helper with one injected retired-model 404,
        # followed by a real API call. This is explicitly not a real outage.
        llm_settings.together_fallback_models = models[:1]
        original_factory = llm_utils._create_llm_client
        original_router = llm_utils.together_router
        sentinel = "smoke-test/retired-model"

        class RetiredClient:
            async def ainvoke(self, *args, **kwargs):
                raise NotFoundError(
                    "Injected retired-model test",
                    response=httpx.Response(
                        404,
                        request=httpx.Request(
                            "POST", "https://api.together.xyz/v1/chat/completions"
                        ),
                    ),
                    body={"error": {"code": "model_not_available"}},
                )

        def factory(**kwargs):
            return (
                RetiredClient()
                if kwargs["model_name"] == sentinel
                else original_factory(**kwargs)
            )

        try:
            llm_utils._create_llm_client = factory
            llm_utils.together_router = TogetherModelRouter()
            reply = await request(
                sentinel, [HumanMessage(content="Reply with: fallback working")]
            )
            data["injected_404_failover"] = {
                "passed": bool(reply.content)
                and reply.response_metadata.get("model_name") in models,
                "served_model": reply.response_metadata.get("model_name"),
                "content": reply.content,
            }
        finally:
            llm_utils._create_llm_client = original_factory
            llm_utils.together_router = original_router
    finally:
        llm_settings.together_fallback_models = original_pool
        data["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()

    passed = all(
        all(case["checks"].values())
        for cases in data["models"].values()
        for case in cases.values()
        if "checks" in case
    )
    passed = passed and data.get("injected_404_failover", {}).get("passed", False)
    print(
        "Review saved content manually for correctness; capability checks:",
        "PASS" if passed else "FAIL",
    )
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.output)))
