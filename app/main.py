from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
import logging

from app.security import signature_required
from app.services.whatsapp_service import whatsapp_client

logger = logging.getLogger(__name__)

# Create a FastAPI application instance
app = FastAPI()


@app.get("/webhooks")
async def webhook_get(request: Request) -> JSONResponse:
    logger.debug("webhook_get is being called")
    return whatsapp_client.verify(request)


@app.post("/webhooks", dependencies=[Depends(signature_required)])
async def webhook_post(request: Request) -> JSONResponse:
    logger.debug("webhook_post is being called")
    return await whatsapp_client.handle_request(request)
