# webhook.py
import os
from fastapi import FastAPI, Request, Response
from app.whatsapp_client import WhatsAppClient

app = FastAPI()

WHATSAPP_HOOK_TOKEN = os.environ.get("WHATSAPP_HOOK_TOKEN")


@app.get("/")
def I_am_alive():
    return "I am alive!!"


@app.get("/webhook/")
def subscribe(request: Request):
    print("subscribe is being called")
    if request.query_params.get("hub.verify_token") == WHATSAPP_HOOK_TOKEN:
        return int(request.query_params.get("hub.challenge"))
    return "Authentication failed. Invalid Token."


@app.post("/webhook/")
async def callback(request: Request):
    print("callback is being called")
    wtsapp_client = WhatsAppClient()
    data = await request.json()
    print("We received " + str(data))
    response = wtsapp_client.process_notification(data)
    if response["statusCode"] == 200:
        if response["body"] and response["from_no"]:
            reply = response["body"]
            print("\nreply is:" + reply)
            wtsapp_client.send_text_message(
                message=reply,
                phone_number=response["from_no"],
            )
            print("\nreply is sent to whatsapp cloud:" + str(response))

    return {"status": "success"}, 200
