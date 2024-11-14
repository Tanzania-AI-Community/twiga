from fastapi import FastAPI, HTTPException, Request, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
import logging
from contextlib import asynccontextmanager

from app.security import signature_required
from app.security import flows_signature_required
from app.services.whatsapp_service import whatsapp_client
from app.services.messaging_service import handle_request
from app.services.flow_service import flow_client
from app.database.engine import db_engine, get_session, init_db
from app.utils.background_tasks_utils import add_background_task
from app.utils.flows_util import decrypt_flow_token

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Initialize database during startup
        await init_db()
        logger.info("Database initialized successfully")

        # Additional startup tasks can go here
        logger.info("Application startup completed")
        yield
    except Exception as e:
        logger.error(f"Error during startup: {e}")
        raise
    finally:
        # Cleanup
        await db_engine.dispose()
        logger.info("Database connections closed")


# Create a FastAPI application instance
app = FastAPI(lifespan=lifespan)

logger.info("FastAPI app initialized")


@app.get("/webhooks")
async def webhook_get(request: Request) -> JSONResponse:
    logger.debug("webhook_get is being called")
    return whatsapp_client.verify(request)


@app.post("/webhooks", dependencies=[Depends(signature_required)])
async def webhook_post(request: Request) -> JSONResponse:
    logger.debug("webhook_post is being called")
    return await handle_request(request)


@app.post("/flows", dependencies=[Depends(flows_signature_required)])
async def handle_flows_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    logger.debug(f"Received webhook: {body}")
    return await flow_client.handle_flow_webhook(body, background_tasks)
