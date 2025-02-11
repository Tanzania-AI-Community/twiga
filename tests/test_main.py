from fastapi import FastAPI
import pytest
from unittest.mock import AsyncMock, patch

from app.config import settings, Environment
from app.main import lifespan


@pytest.mark.asyncio
async def test_lifespan_success() -> None:
    """Lifespan runs successfully with proper setup"""
    app = FastAPI()

    mock_db = AsyncMock()
    mock_engine = AsyncMock()
    mock_engine.dispose = AsyncMock()
    mock_redis_init = AsyncMock()
    mock_redis_disconnect = AsyncMock()

    settings.environment = Environment.PRODUCTION

    with (
        patch("app.main.init_db", mock_db),
        patch("app.main.db_engine", mock_engine),
        patch("app.main.logger") as mock_logger,
        patch("app.main.init_redis", mock_redis_init),
        patch("app.main.disconnect_redis", mock_redis_disconnect),
    ):
        async with lifespan(app):
            pass

        mock_db.assert_awaited_once()
        mock_logger.info.assert_any_call("Database initialized successfully ✅")
        mock_logger.info.assert_any_call("Redis initialized successfully ✅")
        mock_logger.info.assert_any_call("Application startup completed ✅ 🦒")

        mock_engine.dispose.assert_awaited_once()
        mock_logger.info.assert_any_call("Database connections closed 🔒")
        mock_redis_disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_init_db_failure() -> None:
    """Lifespan logs error when init_db() fails"""
    app = FastAPI()

    mock_db = AsyncMock()
    mock_engine = AsyncMock()
    mock_engine.dispose = AsyncMock()
    mock_redis_disconnect = AsyncMock()

    settings.environment = Environment.PRODUCTION

    with (
        patch("app.main.init_db", mock_db),
        patch("app.main.db_engine", mock_engine),
        patch("app.main.logger") as mock_logger,
        patch("app.main.disconnect_redis", mock_redis_disconnect),
        pytest.raises(Exception),
    ):
        async with lifespan(app):
            pass

        mock_db.assert_awaited_once()
        mock_engine.dispose.assert_awaited_once()
        mock_redis_disconnect.assert_awaited_once()

        mock_logger.error.assert_any_call("Error during startup: DB Init Failed ❌")
        mock_logger.info.assert_any_call("Database connections closed 🔒")


@pytest.mark.asyncio
async def test_lifespan_dispose_failure() -> None:
    """Lifespan when init_db() and db_engine.dispose() fail"""
    app = FastAPI()

    mock_db = AsyncMock()
    mock_db.side_effect = Exception("DB Init Failed")

    mock_engine = AsyncMock()

    mock_engine.dispose = AsyncMock()
    mock_engine.dispose.side_effect = Exception("Dispose Failed")

    mock_redis_disconnect = AsyncMock()
    mock_redis_disconnect.side_effect = Exception("This is useless")

    settings.environment = Environment.PRODUCTION

    with (
        patch("app.main.init_db", mock_db),
        patch("app.main.db_engine", mock_engine),
        patch("app.main.logger") as mock_logger,
        patch("app.main.disconnect_redis", mock_redis_disconnect),
        pytest.raises(Exception),
    ):
        async with lifespan(app):
            pass

        mock_db.assert_awaited_once()
        mock_engine.dispose.assert_awaited_once()

        mock_logger.info.assert_not_called()
