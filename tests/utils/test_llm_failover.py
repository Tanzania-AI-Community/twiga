import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import SecretStr, ValidationError

from app.config import LLMProvider, LLMSettings
from app.utils import llm_utils
from app.utils.llm_failover import (
    ModelsCoolingDownError,
    TogetherModelRouter,
    is_availability_error,
    retry_after_seconds,
)


def api_error(status, code=None):
    return APIStatusError(
        "provider error",
        response=httpx.Response(
            status,
            request=httpx.Request(
                "POST", "https://api.together.xyz/v1/chat/completions"
            ),
        ),
        body={"error": {"code": code}},
    )


@pytest.mark.parametrize("status", [404, 410, 408, 429, 500, 502, 503, 504, 524, 529])
def test_availability_statuses(status):
    assert is_availability_error(api_error(status))


@pytest.mark.parametrize("status", [400, 401, 402, 403, 413, 422])
def test_request_and_account_errors_do_not_fail_over(status):
    assert not is_availability_error(api_error(status))


@pytest.mark.parametrize("status", [400, 403])
def test_explicit_model_access_code_can_fail_over(status):
    assert is_availability_error(api_error(status, "model_not_available"))


def test_account_quota_is_not_a_model_outage():
    assert not is_availability_error(api_error(429, "insufficient_quota"))


def test_model_specific_privacy_restriction_allows_another_model():
    assert is_availability_error(api_error(403, "third_party_data_sharing_blocked"))


@pytest.mark.parametrize(
    "header,expected", [("120", 120), ("bad", 0), ("NaN", 0), ("-2", 0)]
)
def test_retry_after_seconds_header(header, expected):
    error = api_error(429)
    error.response.headers["Retry-After"] = header
    assert retry_after_seconds(error) == expected


def test_retry_after_http_date(monkeypatch):
    error = api_error(503)
    error.response.headers["Retry-After"] = "Thu, 01 Jan 1970 00:02:00 GMT"
    monkeypatch.setattr("app.utils.llm_failover.time", MagicMock(time=lambda: 100))
    assert retry_after_seconds(error) == 20


@pytest.mark.parametrize("error", [ValueError("bad JSON"), RuntimeError("bug")])
def test_programming_and_output_errors_are_not_availability_failures(error):
    assert not is_availability_error(error)


@pytest.fixture
def router():
    return TogetherModelRouter()


async def route(router, models, invoke, **overrides):
    options = dict(
        scope=("endpoint", "credential-hash"),
        attempt_timeout=1,
        total_timeout=5,
        cooldown_seconds=60,
    )
    options.update(overrides)
    return await router.request(models, invoke, **options)


@pytest.mark.asyncio
async def test_primary_success_does_not_call_fallback(router):
    result = AIMessage(content="hello")
    invoke = AsyncMock(return_value=result)
    assert await route(router, ["primary", "backup"], invoke) is result
    invoke.assert_awaited_once_with("primary", 1)


@pytest.mark.asyncio
async def test_retired_primary_tries_ordered_unique_models(router):
    result = AIMessage(content='{"answer": 5}')
    invoke = AsyncMock(side_effect=[api_error(404), api_error(503), result])
    assert (
        await route(router, ["primary", "primary", "second", "third"], invoke) is result
    )
    assert [c.args[0] for c in invoke.await_args_list] == ["primary", "second", "third"]


@pytest.mark.asyncio
async def test_can_reach_fifth_model_and_return_native_tool_call(router):
    result = AIMessage(
        content="",
        tool_calls=[{"id": "c1", "name": "lookup", "args": {"topic": "water"}}],
    )
    invoke = AsyncMock(
        side_effect=[
            api_error(404),
            api_error(503),
            api_error(429),
            api_error(410),
            result,
        ]
    )
    models = ["first", "second", "third", "fourth", "fifth"]
    assert await route(router, models, invoke) is result
    assert [call.args[0] for call in invoke.await_args_list] == models


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 402, 403, 422])
async def test_nonavailability_error_stops_without_fallback_or_cooldown(router, status):
    error = api_error(status)
    invoke = AsyncMock(side_effect=error)
    with pytest.raises(APIStatusError) as caught:
        await route(router, ["primary", "backup"], invoke)
    assert caught.value is error
    assert invoke.await_count == 1
    assert router._cooldowns == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [APIConnectionError, APITimeoutError])
async def test_sdk_transport_failures_fail_over(router, error_type):
    error = error_type(request=httpx.Request("POST", "https://api.together.xyz"))
    result = AIMessage(content="recovered")
    invoke = AsyncMock(side_effect=[error, result])
    assert await route(router, ["primary", "backup"], invoke) is result


@pytest.mark.asyncio
async def test_hung_call_is_cancelled_before_fallback(router):
    cancelled = asyncio.Event()
    calls = []

    async def invoke(model, timeout):
        calls.append(model)
        if model == "primary":
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return AIMessage(content="backup answer")

    result = await route(router, ["primary", "backup"], invoke, attempt_timeout=0.01)
    assert result.content == "backup answer"
    assert cancelled.is_set()
    assert calls == ["primary", "backup"]


@pytest.mark.asyncio
async def test_total_budget_limits_attempt_even_with_larger_per_attempt_timeout(router):
    invoke = AsyncMock(side_effect=lambda *args: None)

    async def hang(model, timeout):
        await asyncio.Event().wait()

    invoke.side_effect = hang
    with pytest.raises(TimeoutError):
        await route(router, ["primary", "backup"], invoke, total_timeout=0.01)
    assert invoke.await_count == 1
    assert 0 < invoke.await_args.args[1] <= 0.01


@pytest.mark.asyncio
async def test_cancellation_does_not_call_another_model(router):
    invoke = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await route(router, ["primary", "backup"], invoke)
    assert invoke.await_count == 1
    assert not router._cooldowns


@pytest.mark.asyncio
async def test_cooldown_skips_failed_model_then_retries_it(router, monkeypatch):
    clock = [100.0]
    # Patch only this module's clock, not the event loop's monotonic clock.
    monkeypatch.setattr(
        "app.utils.llm_failover.time", MagicMock(monotonic=lambda: clock[0])
    )
    invoke = AsyncMock(side_effect=[api_error(404), AIMessage(content="backup")])
    await route(router, ["primary", "backup"], invoke)
    invoke = AsyncMock(return_value=AIMessage(content="available"))
    await route(router, ["primary", "backup"], invoke)
    assert invoke.await_args.args[0] == "backup"
    clock[0] += 61
    await route(router, ["primary", "backup"], invoke)
    assert invoke.await_args.args[0] == "primary"


@pytest.mark.asyncio
async def test_all_models_fail_once_then_fail_fast_during_cooldown(router):
    last = api_error(503)
    invoke = AsyncMock(side_effect=[api_error(404), last])
    with pytest.raises(APIStatusError) as caught:
        await route(router, ["primary", "backup"], invoke)
    assert caught.value is last
    assert invoke.await_count == 2
    invoke.reset_mock()
    with pytest.raises(ModelsCoolingDownError) as caught:
        await route(router, ["primary", "backup"], invoke)
    assert 0 < caught.value.retry_after <= 60
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_after_extends_model_cooldown(router):
    error = api_error(429)
    error.response.headers["Retry-After"] = "120"
    with pytest.raises(APIStatusError):
        await route(router, ["primary"], AsyncMock(side_effect=error))
    with pytest.raises(ModelsCoolingDownError) as caught:
        await route(router, ["primary"], AsyncMock())
    assert 110 < caught.value.retry_after <= 120


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope", [("different-endpoint", "credential-hash"), ("endpoint", "other-key")]
)
async def test_health_state_does_not_cross_endpoint_or_credential(router, scope):
    with pytest.raises(APIStatusError):
        await route(router, ["primary"], AsyncMock(side_effect=api_error(404)))
    invoke = AsyncMock(return_value=AIMessage(content="ok"))
    await route(router, ["primary"], invoke, scope=scope)
    invoke.assert_awaited_once()


@pytest.fixture
def together_settings(monkeypatch, router):
    settings = LLMSettings(
        _env_file=None,
        llm_provider="together",
        llm_api_key="test-key",
        llm_model_name="primary",
        llm_fallback_models=["backup"],
    )
    monkeypatch.setattr(llm_utils, "llm_settings", settings)
    monkeypatch.setattr(llm_utils, "together_router", router)
    return settings


@pytest.mark.asyncio
async def test_chat_failover_preserves_tool_history_arguments_json_and_trace(
    together_settings, monkeypatch
):
    together_settings.langsmith_tracing = True
    messages = [
        HumanMessage(content="Solve the equation"),
        AIMessage(
            content="",
            tool_calls=[{"name": "solve_equation", "args": {}, "id": "call-1"}],
        ),
        ToolMessage(content="x=5", tool_call_id="call-1"),
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "solve_equation",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    result = AIMessage(content='{"answer": 5}')
    clients = [
        MagicMock(ainvoke=AsyncMock(side_effect=api_error(404))),
        MagicMock(ainvoke=AsyncMock(return_value=result)),
    ]
    factory = MagicMock(side_effect=clients)
    tracker = MagicMock()
    monkeypatch.setattr(llm_utils, "_create_llm_client", factory)
    monkeypatch.setattr(llm_utils, "LLMCallTracker", tracker)
    response = await llm_utils.async_llm_request(
        messages,
        tools=tools,
        tool_choice="auto",
        run_name="exam",
        metadata={"topic": "water"},
        timeout=180,
        max_tokens=8000,
        response_format={"type": "json_object"},
    )
    assert response is result
    assert [c.kwargs["model_name"] for c in factory.call_args_list] == [
        "primary",
        "backup",
    ]
    assert [c.args for c in tracker.call_args_list] == [
        ("together", "primary"),
        ("together", "backup"),
    ]
    for i, client in enumerate(clients):
        assert client.ainvoke.await_args.args[0] is messages
        params = client.ainvoke.await_args.kwargs
        assert params["max_tokens"] == 8000
        assert params["response_format"] == {"type": "json_object"}
        assert params["config"]["run_name"] == "exam"
        assert params["config"]["metadata"]["topic"] == "water"
        assert params["config"]["metadata"]["llm_model"] == ["primary", "backup"][i]
        assert factory.call_args_list[i].kwargs["tools"] is tools
        assert factory.call_args_list[i].kwargs["tool_choice"] == "auto"
        assert 0 < factory.call_args_list[i].kwargs["timeout"] <= 60


@pytest.mark.asyncio
async def test_equation_override_uses_same_pool_and_its_own_key(
    together_settings, monkeypatch
):
    from app.config import ToolLLMConfig
    from app.tools.tool_code.solve_equation import main as solver

    config = ToolLLMConfig(
        tool_model_name="equation-primary",
        provider="together",
        api_key=SecretStr("tool-key"),
    )
    monkeypatch.setattr(solver.tool_settings, "solve_equation", config)
    monkeypatch.setattr(solver, "async_llm_request", llm_utils.async_llm_request)
    clients = [
        MagicMock(ainvoke=AsyncMock(side_effect=api_error(404))),
        MagicMock(ainvoke=AsyncMock(return_value=AIMessage(content="x=5"))),
    ]
    factory = MagicMock(side_effect=clients)
    monkeypatch.setattr(llm_utils, "_create_llm_client", factory)
    assert await solver.solve_equation("3x+7=22") == "x=5"
    assert [c.kwargs["model_name"] for c in factory.call_args_list] == [
        "equation-primary",
        "backup",
    ]
    assert all(
        c.kwargs["api_key"] == SecretStr("tool-key") for c in factory.call_args_list
    )


@pytest.mark.asyncio
async def test_non_together_provider_does_not_use_together_pool(
    together_settings, monkeypatch
):
    together_settings.provider = LLMProvider.OPENAI
    factory = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(return_value=AIMessage(content="ok")))
    )
    monkeypatch.setattr(llm_utils, "_create_llm_client", factory)
    router = AsyncMock()
    monkeypatch.setattr(llm_utils, "together_router", router)
    await llm_utils.async_llm_request([HumanMessage(content="hello")])
    factory.assert_called_once()
    router.request.assert_not_awaited()


def test_together_sdk_retries_are_disabled(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr(llm_utils, "ChatTogether", constructor)
    llm_utils._create_llm_client(
        LLMProvider.TOGETHER, "model", SecretStr("test"), base_url="https://endpoint"
    )
    assert constructor.call_args.kwargs["max_retries"] == 0
    assert constructor.call_args.kwargs["base_url"] == "https://endpoint"


def test_real_together_client_accepts_default_endpoint_without_network():
    client = llm_utils._create_llm_client(
        LLMProvider.TOGETHER, "model", SecretStr("test"), base_url=None
    )
    assert client.max_retries == 0
    assert client.together_api_base.startswith("https://api.together.")


def test_environment_pool_override_and_blank_primary(monkeypatch):
    monkeypatch.delenv("LLM_FALLBACK_MODELS", raising=False)
    assert LLMSettings(_env_file=None).together_fallback_models == [
        "deepseek-ai/DeepSeek-V4.1-Flash"
    ]
    monkeypatch.setenv(
        "LLM_FALLBACK_MODELS", json.dumps([" second ", "second", "third"])
    )
    monkeypatch.setenv("LLM_MODEL_NAME", "  ")
    settings = LLMSettings(_env_file=None)
    assert settings.together_fallback_models == ["second", "third"]
    assert settings.llm_name == "zai-org/GLM-5.3-Flash"
    monkeypatch.setenv("LLM_FALLBACK_MODELS", "[]")
    assert LLMSettings(_env_file=None).together_fallback_models == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"llm_fallback_models": [" "]},
        {"llm_fallback_models": [str(i) for i in range(5)]},
        {"llm_failover_attempt_timeout": 0},
        {"llm_failover_total_timeout": -1},
        {"llm_failover_cooldown_seconds": -1},
        {"llm_failover_total_timeout": float("inf")},
    ],
)
def test_invalid_failover_settings_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        LLMSettings(_env_file=None, **kwargs)
