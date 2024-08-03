from datetime import datetime
import threading
import logging
from typing import Any
from fastapi import Response

from db.utils import get_message_count, increment_message_count

logger = logging.getLogger(__name__)

# TODO: Change the way we deal with rate limiting
# Initialize the in-memory dictionary to store message counts
message_counts = {}


def is_rate_limit_reached(wa_id: str) -> bool:

    count, last_message_time = get_message_count(wa_id)
    # Reset the message count if it's a new day
    if datetime.now().date() > last_message_time.date():
        count = 0

    # Check if the wa_id has sent more than 5 messages today
    daily_message_limit = 20
    if count >= daily_message_limit:
        return True

    # Increment the message count (this also handles new day resets)
    increment_message_count(wa_id)

    return False


# Function to reset counts at midnight (optional, if running a persistent service)
def reset_counts():
    now = datetime.now()
    midnight = datetime.combine(now.date(), datetime.time())
    seconds_until_midnight = (midnight + datetime.timedelta(days=1) - now).seconds
    threading.Timer(seconds_until_midnight, reset_counts).start()
    message_counts.clear()


def log_http_response(response: Response) -> str:
    logger.info("HTTP response")
    logger.info(f"Status: {response.status_code}")
    logger.info(f"Content-type: {response.headers.get('content-type')}")
    logger.info(f"Body: {response.text}")


async def log_aiohttp_response(response):
    logger.info(f"Response URL: {response.url}")
    logger.info(f"Response Status: {response.status}")
    logger.info(f"Response Headers: {response.headers}")
    logger.info(f"Response Body: {await response.text()}")
