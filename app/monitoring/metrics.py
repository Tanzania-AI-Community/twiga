import time
from typing import Literal, Optional

from prometheus_client import Counter, Histogram
from functools import wraps
from typing import Callable


LLM_LATENCY_BUCKETS = (0.25, 0.5, 1, 2, 4, 8, 16)

whatsapp_webhook_requests_total = Counter(
    "twiga_whatsapp_webhook_requests_total",
    "Count of WhatsApp webhook requests by event type.",
    ["event"],
)

llm_calls_total = Counter(
    "twiga_llm_calls_total",
    "Total LLM calls by provider, model and outcome.",
    ["provider", "model", "outcome"],
)

llm_latency_seconds = Histogram(
    "twiga_llm_latency_seconds",
    "LLM call latency in seconds.",
    ["provider", "model"],
    buckets=LLM_LATENCY_BUCKETS,
)

ratelimit_hits_total = Counter(
    "twiga_ratelimit_hits_total",
    "Rate limit counter increments by scope.",
    ["scope"],
)

ratelimit_blocks_total = Counter(
    "twiga_ratelimit_blocks_total",
    "Rate limit blocks by scope.",
    ["scope"],
)

messages_generated_total = Counter(
    "twiga_messages_generated_total",
    "Number of messages generated for users, grouped by feature.",
    ["feature"],
)


def record_whatsapp_event(event: str) -> None:
    """Increment webhook request counter for the provided event name."""
    whatsapp_webhook_requests_total.labels(event=event).inc()


def record_llm_call(
    provider: str, model: str, outcome: Literal["success", "error"], duration: float
) -> None:
    """Record LLM call outcome and latency."""
    llm_calls_total.labels(provider=provider, model=model, outcome=outcome).inc()
    # Guard against negative durations if called incorrectly.
    llm_latency_seconds.labels(provider=provider, model=model).observe(
        max(duration, 0.0)
    )


def record_rate_limit_hit(scope: Literal["user", "global"]) -> None:
    """Record a rate limit counter increment for the provided scope."""
    ratelimit_hits_total.labels(scope=scope).inc()


def record_rate_limit_block(scope: Literal["user", "global"]) -> None:
    """Record a rate limit block for the provided scope."""
    ratelimit_blocks_total.labels(scope=scope).inc()


def record_messages_generated(feature: str, count: int = 1) -> None:
    """Track generated messages for a given feature."""
    if count < 1:
        return
    messages_generated_total.labels(feature=feature).inc(count)


def track_messages(feature: str, *, count: int = 1) -> Callable:
    """
    Decorator to record message generation for a fixed feature.
    Optional static count can be provided; defaults to 1.
    """

    def decorator(fn: Callable):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            result = await fn(*args, **kwargs)
            record_messages_generated(feature, count)
            return result

        return wrapper

    return decorator


class LLMCallTracker:
    """Helper context manager to measure LLM latency and outcome."""

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        self._start: Optional[float] = None

    def __enter__(self) -> "LLMCallTracker":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._start is None:
            return
        duration = time.perf_counter() - self._start
        outcome: Literal["success", "error"] = "success" if exc is None else "error"
        record_llm_call(self.provider, self.model, outcome, duration)
