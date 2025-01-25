from fastapi import (
    FastAPI,
    Request,
    Depends,
    BackgroundTasks,
    Response,
)
from fastapi.responses import JSONResponse, PlainTextResponse
import logging
from contextlib import asynccontextmanager

from app.security import signature_required
from app.security import flows_signature_required
from app.services.whatsapp_service import whatsapp_client
from app.services.request_service import handle_request
from app.database.engine import db_engine, init_db
from app.services.flow_service import flow_client
from app.services.rate_limit_service import rate_limit
from app.redis.engine import init_redis, disconnect_redis

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Initialize database during startup
        await init_db()
        logger.info("Database initialized successfully ✅")

        # Initialize Redis
        await init_redis()
        logger.info("Redis initialized successfully ✅")

        # Additional startup tasks can go here
        logger.info("Application startup completed ✅ 🦒")
        yield
    except Exception as e:
        logger.error(f"Error during startup: {e} ❌")
        raise
    finally:
        # Cleanup
        await db_engine.dispose()
        logger.info("Database connections closed 🔒")

        # Close Redis connection
        await disconnect_redis()


# Create a FastAPI application instance
app = FastAPI(lifespan=lifespan)

logger.info("FastAPI app initialized successfully ✅")


@app.get("/webhooks")
async def webhook_get(request: Request) -> Response:
    logger.debug("webhook_get is being called")
    return whatsapp_client.verify(request)


@app.post("/webhooks", dependencies=[Depends(signature_required), Depends(rate_limit)])
async def webhook_post(request: Request) -> JSONResponse:
    logger.debug("webhook_post is being called")
    return await handle_request(request)


@app.post("/flows", dependencies=[Depends(flows_signature_required)])
async def handle_flows_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> PlainTextResponse:
    logger.debug("flows webhook is being called")
    return await flow_client.handle_flow_request(request, background_tasks)
