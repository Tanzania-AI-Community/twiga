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
from app.config import settings, Environment

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Initialize database during startup
        await init_db()
        logger.info("Database initialized successfully ✅")

        # Only initialize Redis in production
        if settings.environment in (Environment.PRODUCTION, Environment.STAGING):
            await init_redis()
            logger.info("Redis initialized successfully ✅")

        # CHECK if we starting with a mock whatsapp
        if settings.mock_whatsapp:
            logger.warning("Starting with mock whatsapp enabled ⚠️")
        else:
            logger.info("Starting with mock whatsapp disabled")

        logger.info("Application startup completed ✅ 🦒")
        yield
    except Exception as e:
        logger.error(f"Error during startup: {e} ❌")
        raise
    finally:
        await db_engine.dispose()
        logger.info("Database connections closed 🔒")

        if settings.environment in (Environment.PRODUCTION, Environment.STAGING):
            await disconnect_redis()


# Create a FastAPI application instance
app = FastAPI(lifespan=lifespan)

logger.info("FastAPI app initialized successfully ✅")


@app.get("/webhooks")
async def webhook_get(request: Request) -> Response:
    logger.debug("webhook_get is being called")
    return whatsapp_client.verify(request)


@app.post("/webhooks", dependencies=[Depends(signature_required)])
async def webhook_post(request: Request) -> JSONResponse:
    logger.debug("webhook_post is being called")

    # Check rate limit directly
    if settings.environment in (Environment.PRODUCTION, Environment.STAGING):
        rate_limit_response = await rate_limit(request)

        if rate_limit_response:
            return rate_limit_response

    return await handle_request(request)


@app.post("/devhooks")
async def devhooks_post(request: Request) -> JSONResponse:
    logger.debug("devhooks_post is being called")

    if not settings.mock_whatsapp:
        logger.warning("mock whatsapp is disabled")
        return JSONResponse(content={"message": "mock whatsapp is disabled"})
    return await handle_request(request)


@app.post("/flows", dependencies=[Depends(flows_signature_required)])
async def handle_flows_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> PlainTextResponse:
    logger.debug("flows webhook is being called")
    return await flow_client.handle_flow_request(request, background_tasks)


@app.get("/health")
async def health_check() -> PlainTextResponse:
    return PlainTextResponse("OK")
