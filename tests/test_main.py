from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.testclient import TestClient
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import settings, Environment
from app.main import app, lifespan
from app.security import flows_signature_required, signature_required


@pytest.mark.asyncio
async def test_lifespan_success() -> None:
    """Lifespan runs successfully with proper setup"""
    app = FastAPI()

    mock_db = AsyncMock()
    mock_engine = AsyncMock()
    mock_engine.dispose = AsyncMock()
    mock_redis_init = AsyncMock()
    mock_redis_disconnect = AsyncMock()

    settings.environment = Environment.STAGING

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

    settings.environment = Environment.STAGING

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

    settings.environment = Environment.STAGING

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


@pytest.mark.asyncio
async def test_webhook_get_ok() -> None:
    mock_whatsapp_client = MagicMock()
    mock_whatsapp_client.verify.return_value = PlainTextResponse(
        content="This is a test"
    )

    with (
        patch("app.main.whatsapp_client", mock_whatsapp_client),
        patch("app.main.logger") as mock_logger,
    ):
        client = TestClient(app)

        response = client.get("/webhooks")

        mock_logger.debug.assert_any_call("webhook_get is being called")
        assert response.status_code == 200
        assert response.text == "This is a test"

    assert mock_whatsapp_client.verify.call_count == 1
    args, _ = mock_whatsapp_client.verify.call_args
    assert isinstance(args[0], Request)


@pytest.mark.asyncio
async def test_webhook_post_ok() -> None:
    async def mock_signature_required():
        return None

    app.dependency_overrides[signature_required] = mock_signature_required

    rate_limit_mock = AsyncMock(
        return_value=JSONResponse(
            content={"message": "Rate limit exceeded"}, status_code=200
        )
    )
    mock_handle_request = AsyncMock(
        return_value=JSONResponse(
            content={"message": "This is a test"}, status_code=200
        )
    )

    settings.environment = Environment.DEVELOPMENT

    with (
        patch("app.main.handle_request", mock_handle_request),
        patch("app.main.rate_limit", rate_limit_mock),
        patch("app.main.logger") as mock_logger,
    ):
        client = TestClient(app)

        response = client.post("/webhooks")

        mock_logger.debug.assert_any_call("webhook_post is being called")
        assert response.status_code == 200
        assert response.json() == {"message": "This is a test"}

    assert mock_handle_request.call_count == 1
    args, _ = mock_handle_request.call_args
    assert isinstance(args[0], Request)

    rate_limit_mock.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_post_hits_rate_limit() -> None:
    async def mock_signature_required():
        return None

    app.dependency_overrides[signature_required] = mock_signature_required

    rate_limit_mock = AsyncMock(
        return_value=JSONResponse(
            content={"message": "Rate limit exceeded"}, status_code=200
        )
    )
    mock_handle_request = AsyncMock(
        return_value=JSONResponse(
            content={"message": "This is a test"}, status_code=200
        )
    )

    settings.environment = Environment.STAGING

    with (
        patch("app.main.handle_request", mock_handle_request),
        patch("app.main.rate_limit", rate_limit_mock),
        patch("app.main.logger") as mock_logger,
    ):
        client = TestClient(app)

        response = client.post("/webhooks")

        mock_logger.debug.assert_any_call("webhook_post is being called")
        assert response.status_code == 200
        assert response.json() == {"message": "Rate limit exceeded"}

    assert rate_limit_mock.call_count == 1
    args, _ = rate_limit_mock.call_args
    assert isinstance(args[0], Request)

    mock_handle_request.assert_not_called()


@pytest.mark.asyncio
async def test_handle_flows_webhook_ok() -> None:
    async def mock_flows_signature_required():
        return None

    # app = FastAPI()
    app.dependency_overrides[flows_signature_required] = mock_flows_signature_required

    mock_flow_client = AsyncMock()
    mock_flow_client.handle_flow_request = AsyncMock(
        return_value=PlainTextResponse(content="This is a test")
    )

    with (
        patch("app.main.logger") as mock_logger,
        patch("app.main.flow_client", mock_flow_client),
    ):
        client = TestClient(app)

        response = client.post("/flows")

        mock_logger.debug.assert_any_call("flows webhook is being called")
        assert response.status_code == 200
        assert response.text == "This is a test"

    assert mock_flow_client.handle_flow_request.call_count == 1
    args, _ = mock_flow_client.handle_flow_request.call_args
    assert isinstance(args[0], Request)
    assert isinstance(args[1], BackgroundTasks)


@pytest.mark.asyncio
async def test_health_check_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.text == "OK"
