"""
WhatsApp client helper for cron jobs.

This module provides a standalone WhatsApp client for sending
template messages without depending on the main application.
"""

import os
import logging
from typing import Optional

import httpx


class WhatsAppClient:
    """
    Standalone WhatsApp client for cron job operations.

    Handles sending template messages to users via WhatsApp Business API.
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        api_version: Optional[str] = None,
        mock: bool = False,
    ):
        """
        Initialize WhatsApp client.

        Args:
            api_token: WhatsApp API token (defaults to env var)
            phone_number_id: WhatsApp Business phone number ID (defaults to env var)
            api_version: Meta API version (defaults to env var)
            mock: If True, skip actual API calls

        Raises:
            ValueError: If required credentials are missing
        """
        self.api_token = api_token or os.getenv("WHATSAPP_API_TOKEN")
        self.phone_number_id = phone_number_id or os.getenv("WHATSAPP_CLOUD_NUMBER_ID")
        self.api_version = api_version or os.getenv("META_API_VERSION")
        self.mock = mock or os.getenv("MOCK_WHATSAPP", "false").lower() in (
            "true",
            "1",
            "yes",
        )

        # Validate required credentials
        if not self.mock:
            if not self.api_token:
                raise ValueError("WHATSAPP_API_TOKEN is required")
            if not self.phone_number_id:
                raise ValueError("WHATSAPP_CLOUD_NUMBER_ID is required")
            if not self.api_version:
                raise ValueError("META_API_VERSION is required")

        self.headers = {
            "Content-type": "application/json",
            "Authorization": f"Bearer {self.api_token}",
        }
        self.url = (
            f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}"
        )
        self.logger = logging.getLogger(__name__)
        self.client = httpx.AsyncClient(base_url=self.url)

    async def send_template_message(
        self,
        wa_id: str,
        template_name: str,
        language_code: str = "en_US",
    ) -> None:
        """
        Send a WhatsApp template message.

        Args:
            wa_id: WhatsApp ID (phone number) of recipient
            template_name: Name of the approved template message
            language_code: Language code for the template (default: "en_US")

        Raises:
            httpx.HTTPStatusError: If API request fails
            Exception: For other unexpected errors
        """
        if self.mock:
            self.logger.info(f"MOCK: Would send template '{template_name}' to {wa_id}")
            return

        try:
            payload = {
                "messaging_product": "whatsapp",
                "to": wa_id,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": language_code},
                    "components": [
                        {
                            "type": "header",
                            "parameters": [
                                {
                                    "type": "image",
                                    "image": {
                                        "link": "https://twiga.ai.or.tz/external/classroom-image.jpeg"
                                    },
                                }
                            ],
                        }
                    ],
                },
            }

            response = await self.client.post(
                "/messages",
                json=payload,
                headers=self.headers,
            )
            response.raise_for_status()

            self.logger.info(
                f"Template message '{template_name}' sent successfully to {wa_id}"
            )

        except httpx.HTTPStatusError as e:
            self.logger.error(
                f"HTTP error sending template to {wa_id}: {e.response.status_code} - {e.response.text}"
            )
            raise
        except httpx.RequestError as e:
            self.logger.error(f"Request error sending template to {wa_id}: {str(e)}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error sending template to {wa_id}: {e}")
            raise

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


def create_whatsapp_client(
    api_token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    api_version: Optional[str] = None,
    mock: bool = False,
) -> WhatsAppClient:
    """
    Factory function to create a WhatsApp client.

    Args:
        api_token: WhatsApp API token (defaults to env var)
        phone_number_id: WhatsApp Business phone number ID (defaults to env var)
        api_version: Meta API version (defaults to env var)
        mock: If True, skip actual API calls

    Returns:
        WhatsAppClient: Configured WhatsApp client
    """
    return WhatsAppClient(
        api_token=api_token,
        phone_number_id=phone_number_id,
        api_version=api_version,
        mock=mock,
    )
