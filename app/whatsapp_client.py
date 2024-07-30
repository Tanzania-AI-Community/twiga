"""
This script uses the WhatsApp Business API to send messages via HTTP requests.
"""

# whatsapp_client.py
import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()


class WhatsAppWrapper:

    API_URL = "https://graph.facebook.com/v15.0/"
    WHATSAPP_API_TOKEN = os.environ.get("WHATSAPP_API_TOKEN")
    WHATSAPP_CLOUD_NUMBER_ID = os.environ.get("WHATSAPP_CLOUD_NUMBER_ID")

    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {self.WHATSAPP_API_TOKEN}",
            "Content-Type": "application/json",
        }
        self.API_URL = self.API_URL + self.WHATSAPP_CLOUD_NUMBER_ID

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
        print(response.status_code)
        print(response.text)
        assert response.status_code == 200, "Error sending message"
        return response.status_code

        # whatsapp_client.py

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
                                print(
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


if __name__ == "__main__":
    client = WhatsAppWrapper()
    phone_number = os.environ.get("RECIPIENT_WAID")
    # send a template message
    client.send_template_message("hello_world", "en_US", phone_number)
