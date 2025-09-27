import asyncio
from app.services.whatsapp_service import WhatsAppClient


async def main() -> None:
    """
    Test the send image functionality. 
    Make sure your app token is new, your phonenumber is added to your facebook dev - app
    Remember, no "+"!
    """
    your_number = "xxx"  # Your WhatsApp number
    client = WhatsAppClient()
    try:
        await client.send_image_message(
            wa_id=your_number,           # Recipient's WhatsApp number in E.164 format
            image_path="tests/example.jpg", # Absolute/relative path to your image
            mime_type="image/jpeg",          # Must be image/jpeg or image/png
            caption="Wow such captions!",  # Optional message shown under the image
        )
    finally:
        # Close the underlying AsyncClient so the event loop can exit cleanly
        await client.client.aclose()


if __name__ == "__main__":
    asyncio.run(main())