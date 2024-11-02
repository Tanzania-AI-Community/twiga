from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
import logging
from contextlib import asynccontextmanager


from app.security import signature_required
from app.security import flows_signature_required
from app.services.whatsapp_service import whatsapp_client
from app.services.messaging_service import handle_request
from app.services.flow_service import flow_client
from app.database.engine import db_engine, init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Initialize database during startup
        await init_db(db_engine)
        logger.info("Application startup completed")
        yield
    finally:
        await db_engine.dispose()
        logger.info("Database connection closed")


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
async def handle_flows_webhook(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        logger.debug(f"Received webhook: {body}")
        return await flow_client.handle_flow_webhook(body)
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


# use this when testing flows locally, the returned token will be the flow_token
@app.post("/encrypt_flow_token")
async def handle_encrypt_flow_token(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        logger.debug(f"Received request to encrypt flow token: {body}")
        wa_id = body.get("wa_id")
        flow_id = body.get("flow_id")

        logger.info(f"Encrypting flow token for wa_id {wa_id} and flow_id {flow_id}")

        return await flow_client.encrypt_flow_token(wa_id, flow_id)
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

        return await flow_client.decrypt_flow_token(encrypted_flow_token)
    except Exception as e:
        logger.error(f"Error decrypting flow token: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
