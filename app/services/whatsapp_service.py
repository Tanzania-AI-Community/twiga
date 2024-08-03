"""
This script uses the WhatsApp Business API to send messages via HTTP requests.
"""

from datetime import datetime
import os
from typing import Tuple
from fastapi import Request
from fastapi.responses import JSONResponse
import requests
import json
from dotenv import load_dotenv
import logging
import httpx

from app.config import settings
from app.utils.helpers import is_rate_limit_reached, log_aiohttp_response
from app.utils.whatsapp_utils import (
    get_text_message_input,
    is_valid_whatsapp_message,
    process_whatsapp_message,
    process_text_for_whatsapp,
)
from db.utils import store_message
from app.main import app

load_dotenv()

logger = logging.getLogger(__name__)


class WhatsAppClient:

    def __init__(self):
        self.headers = {
            "Content-type": "application/json",
            "Authorization": f"Bearer {settings.whatsapp_api_token}",
        }
        self.url = f"https://graph.facebook.com/{settings.meta_api_version}/{settings.whatsapp_cloud_number_id}"

    def send_template_message(self, template_name, language_code, phone_number):

        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "template",
            "template": {"name": template_name, "language": {"code": language_code}},
        }

        response = requests.post(
            f"{self.API_URL}/messages", json=payload, headers=self.headers
        )

        assert response.status_code == 200, "Error sending message"

        return response.status_code

    def send_text_message(self, message, phone_number):
        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        }
        response = requests.post(
            f"{self.API_URL}/messages", json=payload, headers=self.headers
        )
        logger.info(response.status_code)
        logger.info(response.text)
        assert response.status_code == 200, "Error sending message"
        return response.status_code

    def process_notification(self, data):
        entries = data["entry"]
        for entry in entries:
            for change in entry["changes"]:
                value = change["value"]
                if value:
                    if "messages" in value:
                        for message in value["messages"]:
                            if message["type"] == "text":
                                from_no = message["from"]
                                message_body = message["text"]["body"]
                                prompt = message_body
                                logger.info(
                                    f"Ack from FastAPI-WtsApp Webhook: {message_body}"
                                )
                                return {
                                    "statusCode": 200,
                                    "body": prompt,
                                    "from_no": from_no,
                                    "isBase64Encoded": False,
                                }

        return {
            "statusCode": 403,
            "body": json.dumps("Unsupported method"),
            "isBase64Encoded": False,
        }

    # Required webhook verification for WhatsApp
    def verify(request: Request) -> Tuple[str, int]:
        # Parse params from the webhook verification request
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        # Check if a token and mode were sent
        if mode and token:
            # Check the mode and token sent are correct
            if mode == "subscribe" and token == settings.whatsapp_verify_token:
                # Respond with 200 OK and challenge token from the request
                logger.info("WEBHOOK_VERIFIED")
                return challenge, 200
            else:
                # Responds with '403 Forbidden' if verify tokens do not match
                logger.error("VERIFICATION_FAILED")
                return JSONResponse(
                    content={"status": "error", "message": "Verification failed"},
                    status_code=403,
                )
        else:
            # Responds with '400 Bad Request'
            logger.error("MISSING_PARAMETER")
            return JSONResponse(
                content={"status": "error", "message": "Missing parameters"},
                status_code=400,
            )

    async def handle_message(self, request: Request) -> Tuple[JSONResponse, int]:
        """
        Handle incoming webhook events from the WhatsApp API.

        This function processes incoming WhatsApp messages and other events,
        such as delivery statuses. If the event is a valid message, it gets
        processed. If the incoming payload is not a recognized WhatsApp event,
        an error is returned.

        Every message send will trigger 4 HTTP requests to your webhook: message, sent, delivered, read.

        Returns:
            response: A tuple containing a JSON response and an HTTP status code.
        """
        body = await request.json()

        # Check if it's a WhatsApp status update
        if (
            body.get("entry", [{}])[0]
            .get("changes", [{}])[0]
            .get("value", {})
            .get("statuses")
        ):
            logger.info("Received a WhatsApp status update.")
            return JSONResponse(content={"status": "ok"}, status_code=200)

        try:
            if is_valid_whatsapp_message(body):
                logger.info("Received a valid WhatsApp message.")

                message = body["entry"][0]["changes"][0]["value"]["messages"][0]
                message_timestamp = int(message.get("timestamp"))
                current_timestamp = int(datetime.now().timestamp())

                wa_id = body["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]

                # Check if the message timestamp is within 10 seconds of the current time
                if current_timestamp - message_timestamp <= 10:
                    # Check if the daily message limit has been reached
                    if is_rate_limit_reached(wa_id):
                        logger.warning(f"Message limit reached for wa_id: {wa_id}")
                        sleepy_text = "🚫 You have reached your daily messaging limit, so Twiga 🦒 is quite sleepy 🥱 from all of today's texting. Let's talk more tomorrow!"
                        sleepy_msg = process_text_for_whatsapp(sleepy_text)
                        data = get_text_message_input(
                            wa_id,
                            sleepy_msg,  # could also just use wa_id here instead of going to config
                        )
                        store_message(wa_id, message, role="user")
                        store_message(
                            wa_id,
                            sleepy_text,
                            role="twiga",
                        )
                        await self.send_message(data)

                        return JSONResponse(content={"status": "ok"}, status_code=200)

                    # This function is used to process and ultimately send a response message to the user
                    await process_whatsapp_message(body)
                    return JSONResponse(content={"status": "ok"}, status_code=200)
                else:
                    store_message(wa_id, message, role="user")
                    logger.warning("Received a message with an outdated timestamp.")
                    return JSONResponse(content={"status": "ok"}, status_code=200)

            else:
                # if the request is not a WhatsApp API event, return an error
                return JSONResponse(
                    content={"status": "error", "message": "Not a WhatsApp API event"},
                    status_code=404,
                )
        except json.JSONDecodeError:
            logger.error("Failed to decode JSON")
            return JSONResponse(
                content={"status": "error", "message": "Invalid JSON provided"},
                status_code=400,
            )

    async def send_message(self, data: str) -> None:

        async with httpx.AsyncClient(app=app, base_url=self.url) as session:
            try:
                response = await session.post(
                    "/messages", data=data, headers=self.headers
                )
                if response.status_code == 200:
                    await log_aiohttp_response(response)
                else:
                    logger.info("Response status not OK")
                    logger.info(f"Status: {response.status_code}")
                    logger.info(response.text)  # Log the response text for more details
            except httpx.ConnectError as e:
                logger.error("Connection Error: %s", str(e))
            except httpx.HTTPStatusError as e:
                logger.error("HTTP Status Error: %s", str(e))
            except httpx.RequestError as e:
                logger.error("Request Error: %s", str(e))


whatsapp_client = WhatsAppClient()
