# webhook.py
import os
from fastapi import FastAPI, Request, Response
from app.whatsapp_service import WhatsAppWrapper
import logging

app = FastAPI()

logger = logging.getLogger(__name__)
WHATSAPP_HOOK_TOKEN = os.environ.get("WHATSAPP_HOOK_TOKEN")


@app.get("/")
def I_am_alive():
    return "I am alive!!"


@app.get("/webhook/")
def subscribe(request: Request):
    logger.info("subscribe is being called")
    if request.query_params.get("hub.verify_token") == WHATSAPP_HOOK_TOKEN:
        return int(request.query_params.get("hub.challenge"))
    return "Authentication failed. Invalid Token."


@app.post("/webhook/")
async def callback(request: Request):
    logger.info("callback is being called")
    whatsapp = WhatsAppWrapper()
    data = await request.json()
    logger.info("We received " + str(data))
    response = whatsapp.process_notification(data)
    if response["statusCode"] == 200:
        if response["body"] and response["from_no"]:
            reply = response["body"]
            logger.info("\nreply is:" + reply)
            whatsapp.send_text_message(
                message=reply,
                phone_number=response["from_no"],
            )
            logger.info("\nreply is sent to whatsapp cloud:" + str(response))

    return {"status": "success"}, 200
