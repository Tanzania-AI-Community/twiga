from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse

from app.decorators.security import signature_required
from app.whatsapp_service import WhatsAppWrapper
from app.config import settings

import logging

logger = logging.getLogger(__name__)

app = FastAPI()


# async def handle_message(request: Request) -> Tuple[JSONResponse, int]:
#     """
#     Handle incoming webhook events from the WhatsApp API.

#     This function processes incoming WhatsApp messages and other events,
#     such as delivery statuses. If the event is a valid message, it gets
#     processed. If the incoming payload is not a recognized WhatsApp event,
#     an error is returned.

#     Every message send will trigger 4 HTTP requests to your webhook: message, sent, delivered, read.

#     Returns:
#         response: A tuple containing a JSON response and an HTTP status code.
#     """
#     body = await request.json()

#     # Check if it's a WhatsApp status update
#     if (
#         body.get("entry", [{}])[0]
#         .get("changes", [{}])[0]
#         .get("value", {})
#         .get("statuses")
#     ):
#         logger.info("Received a WhatsApp status update.")
#         return JSONResponse(content={"status": "ok"}, status_code=200)

#     try:
#         if is_valid_whatsapp_message(body):
#             logger.info("Received a valid WhatsApp message.")

#             message = body["entry"][0]["changes"][0]["value"]["messages"][0]
#             message_timestamp = int(message.get("timestamp"))
#             current_timestamp = int(datetime.datetime.now().timestamp())

#             wa_id = body["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]

#             # Check if the message timestamp is within 10 seconds of the current time
#             if current_timestamp - message_timestamp <= 10:
#                 # Check if the daily message limit has been reached
#                 if is_rate_limit_reached(wa_id):
#                     logger.warning(f"Message limit reached for wa_id: {wa_id}")
#                     sleepy_text = "🚫 You have reached your daily messaging limit, so Twiga 🦒 is quite sleepy 🥱 from all of today's texting. Let's talk more tomorrow!"
#                     sleepy_msg = process_text_for_whatsapp(sleepy_text)
#                     data = get_text_message_input(
#                         wa_id,
#                         sleepy_msg,  # could also just use wa_id here instead of going to config
#                     )
#                     store_message(wa_id, message, role="user")
#                     store_message(
#                         wa_id,
#                         sleepy_text,
#                         role="twiga",
#                     )
#                     await send_message(data)

#                     return JSONResponse(content={"status": "ok"}, status_code=200)

#                 # This function is used to process and ultimately send a response message to the user
#                 await process_whatsapp_message(body)
#                 return JSONResponse(content={"status": "ok"}, status_code=200)
#             else:
#                 store_message(wa_id, message, role="user")
#                 logger.warning("Received a message with an outdated timestamp.")
#                 return JSONResponse(content={"status": "ok"}, status_code=200)

#         else:
#             # if the request is not a WhatsApp API event, return an error
#             return JSONResponse(
#                 content={"status": "error", "message": "Not a WhatsApp API event"},
#                 status_code=404,
#             )
#     except json.JSONDecodeError:
#         logger.error("Failed to decode JSON")
#         return JSONResponse(
#             content={"status": "error", "message": "Invalid JSON provided"},
#             status_code=400,
#         )


# # Required webhook verification for WhatsApp
# def verify(request: Request) -> Tuple[str, int]:
#     # Parse params from the webhook verification request
#     mode = request.query_params.get("hub.mode")
#     token = request.query_params.get("hub.verify_token")
#     challenge = request.query_params.get("hub.challenge")
#     # Check if a token and mode were sent
#     if mode and token:
#         # Check the mode and token sent are correct
#         if mode == "subscribe" and token == settings.VERIFY_TOKEN:
#             # Respond with 200 OK and challenge token from the request
#             logger.info("WEBHOOK_VERIFIED")
#             return challenge, 200
#         else:
#             # Responds with '403 Forbidden' if verify tokens do not match
#             logger.error("VERIFICATION_FAILED")
#             return JSONResponse(
#                 content={"status": "error", "message": "Verification failed"},
#                 status_code=403,
#             )
#     else:
#         # Responds with '400 Bad Request'
#         logger.error("MISSING_PARAMETER")
#         return JSONResponse(
#             content={"status": "error", "message": "Missing parameters"},
#             status_code=400,
#         )


@app.get("/webhooks")
async def webhook_get(request: Request):
    logger.info("webhook_get is being called")
    return verify(request)


@app.post("/webhooks")
async def webhook_post(request: Request, _: None = Depends(signature_required)):
    return await handle_message(request)


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
