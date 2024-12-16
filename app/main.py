from fastapi import FastAPI, Request, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
import logging
from contextlib import asynccontextmanager

from app.security import signature_required
from app.security import flows_signature_required
from app.services.whatsapp_service import whatsapp_client
from app.services.request_service import handle_request
from app.database.engine import db_engine, init_db
from fastapi import Request, HTTPException
import app.utils.flow_utils as futil
from app.config import settings


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
    return await handle_request(request, endpoint="webhooks")


@app.post("/flows", dependencies=[Depends(flows_signature_required)])
async def handle_flows_webhook(request: Request, background_tasks: BackgroundTasks):
    logger.debug("flows webhook is being called")
    return await handle_request(request, background_tasks, endpoint="flows")


if settings.environment == "development":
    # use this when testing flows, the returned token will be the flow_token. The ideal way is to use have scripts for these operations
    # the encrypt_flow_token will help you get the flow_token which can be used when testing flows
    # the decrypt_flow_token will help you get the wa_id and flow_id from the encrypted flow_token
    @app.post("/encrypt_flow_token")
    async def handle_encrypt_flow_token(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            logger.debug(f"Received request to encrypt flow token: {body}")
            wa_id = body.get("wa_id")
            flow_id = body.get("flow_id")

            logger.info(
                f"Encrypting flow token for wa_id {wa_id} and flow_id {flow_id}"
            )

            return futil.encrypt_flow_token(wa_id, flow_id)
        except Exception as e:
            logger.error(f"Error encrypting flow token: {e}")
            raise HTTPException(status_code=500, detail="Internal Server Error")

    # decrypt_flow_token
    @app.post("/decrypt_flow_token")
    async def handle_decrypt_flow_token(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            logger.debug(f"Received request to decrypt flow token: {body}")
            encrypted_flow_token = body.get("encrypted-flow-token")

            return futil.decrypt_flow_token(encrypted_flow_token)
        except Exception as e:
            logger.error(f"Error decrypting flow token: {e}")
            raise HTTPException(status_code=500, detail="Internal Server Error")
