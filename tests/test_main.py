import sys
import os

import pytest
from fastapi import FastAPI
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.main import lifespan, db_engine


@pytest.mark.asyncio
async def test_lifespan_success() -> None:
    """Tests lifespan runs successfully with proper setup and cleanup."""
    app = FastAPI()

    with (
        patch(
            "app.database.engine.init_db", new_callable=AsyncMock
        ) as mock_init_db,
        patch(
            "app.main.db_engine.dispose",  new_callable=AsyncMock
        ) as mock_dispose,
        patch("app.main.logger") as mock_logger,
    ):
        async with lifespan(app):
            mock_init_db.assert_awaited_once()
            mock_logger.info.assert_any_call("Database initialized successfully")
            mock_logger.info.assert_any_call("Application startup completed")

        mock_dispose.assert_awaited_once()
        mock_logger.info.assert_any_call("Database connections closed")


@pytest.mark.asyncio
async def test_lifespan_init_db_failure() -> None:
    """Test lifespan when init_db() fails."""
    app = FastAPI()

    mock_db = AsyncMock()
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()

    with (
        patch("app.database.engine.init_db", mock_db),
        patch("app.main.db_engine", mock_engine),
        patch("app.main.logger") as mock_logger,
    ):
        mock_db.side_effect = Exception("DB Init Failed")

        with pytest.raises(Exception):
            async with lifespan(app):
                pass

        mock_db.assert_awaited_once()
        #print(mock_logger.error)
        mock_logger.error.assert_any_call("Error during startup: DB Init Failed")

        mock_engine.dispose.assert_not_awaited()
        mock_logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_dispose_failure() -> None:
    """Test lifespan when db_engine.dispose() fails."""
    app = FastAPI()

    with (
        patch(
            "app.database.engine.init_db", new_callable=AsyncMock
        ) as mock_init_db,
        patch.object(
            db_engine, "dispose", new_callable=AsyncMock
        ) as mock_dispose,
        patch("app.main.logger") as mock_logger,
    ):
        mock_dispose.side_effect = Exception("Dispose Failed")

        with pytest.raises(Exception, match="Dispose Failed"):
            async with lifespan(app):
                pass

        mock_init_db.assert_awaited_once()
        mock_logger.info.assert_any_call("Database initialized successfully")
        mock_logger.info.assert_any_call("Application startup completed")

        mock_dispose.assert_awaited_once()
        mock_logger.error.assert_any_call("Error during cleanup: Dispose Failed")
