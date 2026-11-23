from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.rate_limit_service import RateLimitService


@pytest.mark.asyncio
async def test_rate_limit_counter_does_not_refresh_existing_expiry() -> None:
    pipeline = MagicMock()
    pipeline.set = AsyncMock()
    pipeline.incr = AsyncMock()
    pipeline.execute = AsyncMock(return_value=[False, 2])

    redis = MagicMock()
    redis.pipeline = AsyncMock(return_value=pipeline)

    with (
        patch(
            "app.services.rate_limit_service.is_redis_available",
            return_value=True,
        ),
        patch(
            "app.services.rate_limit_service.get_redis_client",
            return_value=redis,
        ),
        patch("app.services.rate_limit_service.settings.time_to_live", 86400),
        patch("app.services.rate_limit_service.record_rate_limit_hit"),
    ):
        exceeded, count = await RateLimitService()._check_rate_limit(
            key="rate:user:255700000001",
            limit=10,
            scope="user",
        )

    assert exceeded is False
    assert count == 2
    pipeline.set.assert_awaited_once_with(
        "rate:user:255700000001", 0, ex=86400, nx=True
    )
    pipeline.incr.assert_awaited_once_with("rate:user:255700000001")


@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_remaining_fixed_window_ttl() -> None:
    pipeline = MagicMock()
    pipeline.set = AsyncMock()
    pipeline.incr = AsyncMock()
    pipeline.execute = AsyncMock(return_value=[False, 11])

    redis = MagicMock()
    redis.pipeline = AsyncMock(return_value=pipeline)
    redis.ttl = AsyncMock(return_value=3600)

    with (
        patch(
            "app.services.rate_limit_service.is_redis_available",
            return_value=True,
        ),
        patch(
            "app.services.rate_limit_service.get_redis_client",
            return_value=redis,
        ),
        patch("app.services.rate_limit_service.settings.time_to_live", 86400),
        patch("app.services.rate_limit_service.record_rate_limit_hit"),
        patch("app.services.rate_limit_service.record_rate_limit_block"),
    ):
        exceeded, ttl = await RateLimitService()._check_rate_limit(
            key="rate:user:255700000001",
            limit=10,
            scope="user",
        )

    assert exceeded is True
    assert ttl == 3600
    redis.ttl.assert_awaited_once_with("rate:user:255700000001")
