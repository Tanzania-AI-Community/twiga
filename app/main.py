from fastapi import FastAPI, Request, Depends
import logging

from app.decorators.security import signature_required
from app.services.whatsapp_service import whatsapp_client

logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/webhooks")
async def webhook_get(request: Request):
    logger.info("webhook_get is being called")
    return whatsapp_client.verify(request)


@app.post("/webhooks", dependencies=[Depends(signature_required)])
async def webhook_post(request: Request):
    logger.info("webhook_post is being called")
    return await whatsapp_client.handle_message(request)


# @app.get("/")
# def I_am_alive():
#     return "I am alive!!"


# @app.get("/webhook/")
# def subscribe(request: Request):
#     logger.info("subscribe is being called")
#     if request.query_params.get("hub.verify_token") == settings.whatsapp_verify_token:
#         return int(request.query_params.get("hub.challenge"))
#     return "Authentication failed. Invalid Token."


# @app.post("/webhook/")
# async def callback(request: Request):
#     logger.info("callback is being called")
#     whatsapp = WhatsAppWrapper()
#     data = await request.json()
#     logger.info("We received " + str(data))
#     response = whatsapp.process_notification(data)
#     if response["statusCode"] == 200:
#         if response["body"] and response["from_no"]:
#             reply = response["body"]
#             logger.info("\nreply is:" + reply)
#             whatsapp.send_text_message(
#                 message=reply,
#                 phone_number=response["from_no"],
#             )
#             logger.info("\nreply is sent to whatsapp cloud:" + str(response))

#     return {"status": "success"}, 200
