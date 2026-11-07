"""Bounded, ordered failover for Together's OpenAI-compatible API."""

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime

from langchain_core.messages import AIMessage
from openai import APIConnectionError, APIStatusError

logger = logging.getLogger(__name__)


class ModelsCoolingDownError(RuntimeError):
    """All configured models recently failed; do not hammer them on every turn."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(
            f"All configured Together models are cooling down; retry in {retry_after:.1f}s"
        )


def is_availability_error(error: Exception) -> bool:
    if isinstance(error, (APIConnectionError, TimeoutError)):
        return True
    if not isinstance(error, APIStatusError):
        return False
    body = error.body
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    if isinstance(body, dict) and body.get("code") in {
        "insufficient_quota",
        "billing_hard_limit_reached",
    }:
        return False
    if error.status_code in (408, 429) or error.status_code >= 500:
        return True
    # Missing/retired models commonly return 404; 410 also means gone.
    if error.status_code in (404, 410):
        return True
    # Some model-access errors use 400/403. Do not treat a generic 403,
    # invalid credentials, exhausted credit, or invalid payload as failover.
    return (
        error.status_code in (400, 403)
        and isinstance(body, dict)
        and body.get("code")
        in {
            "model_not_available",
            "model_not_found",
            "third_party_data_sharing_blocked",
        }
    )


def retry_after_seconds(error: Exception) -> float:
    """Respect Retry-After without sleeping before trying a different model."""
    if not isinstance(error, APIStatusError):
        return 0
    header = error.response.headers.get("retry-after")
    if not header:
        return 0
    try:
        seconds = float(header)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(header).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return 0
    return max(0, seconds) if math.isfinite(seconds) else 0


class TogetherModelRouter:
    """Cooldown state is local to a worker and scoped by endpoint and credential hash.

    There is no lock held over network I/O. Concurrent requests already in flight
    may see the same failure; later requests skip it until the cooldown expires.
    """

    def __init__(self):
        self._cooldowns: dict[tuple[str, str, str], float] = {}

    async def request(
        self,
        models: list[str],
        invoke: Callable[[str, float], Awaitable[AIMessage]],
        *,
        scope: tuple[str, str],
        attempt_timeout: float,
        total_timeout: float,
        cooldown_seconds: float,
    ) -> AIMessage:
        models = list(dict.fromkeys(model.strip() for model in models))
        if not models or any(not model for model in models):
            raise ValueError("At least one nonblank Together model name is required")
        now = time.monotonic()
        self._cooldowns = {
            key: until for key, until in self._cooldowns.items() if until > now
        }
        deadline = now + total_timeout
        last_error = None
        for model in models:
            key = (*scope, model)
            if self._cooldowns.get(key, 0) > time.monotonic():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "Together model failover time budget exhausted"
                ) from last_error
            timeout = min(attempt_timeout, remaining)
            try:
                response = await asyncio.wait_for(invoke(model, timeout), timeout)
            except Exception as error:
                if not is_availability_error(error):
                    raise
                self._cooldowns[key] = time.monotonic() + max(
                    cooldown_seconds, retry_after_seconds(error)
                )
                last_error = error
                # Do not log payloads, credentials or the provider error body.
                logger.warning(
                    "Together model unavailable: model=%s error=%s status=%s; "
                    "trying the next eligible model within the request budget",
                    model,
                    type(error).__name__,
                    getattr(error, "status_code", None),
                )
            else:
                self._cooldowns.pop(key, None)
                if model != models[0]:
                    logger.info("Together fallback succeeded: model=%s", model)
                return response
        if last_error is not None:
            raise last_error
        retry_after = min(self._cooldowns[(*scope, model)] for model in models)
        raise ModelsCoolingDownError(max(0, retry_after - time.monotonic()))
