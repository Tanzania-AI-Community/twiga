from datetime import datetime
import threading
import logging
from typing import Any
import httpx

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


async def log_httpx_response(response: httpx.Response):
    # ANSI escape code mapping
    ANSI_COLOR_CODES = {
        "green": "32",
        "cyan": "36",
        "yellow": "33",
        "red": "31",
        "reset": "0",
        "magenta": "35",
    }

    # Extracting necessary details from the response
    url = response.url
    status_code = response.status_code
    headers = response.headers
    body = response.text

    # Color formatting based on the status code
    if 200 <= status_code < 300:
        status_color = ANSI_COLOR_CODES["green"]
    elif 300 <= status_code < 400:
        status_color = ANSI_COLOR_CODES["cyan"]
    elif 400 <= status_code < 500:
        status_color = ANSI_COLOR_CODES["yellow"]
    else:
        status_color = ANSI_COLOR_CODES["red"]

    # Logging the details with color coding
    logger.info(f"Response URL: {url}")
    logger.info(f"Response Status: \033[{status_color}m{status_code}\033[0m")
    # logger.info("Response Headers:")
    # for key, value in headers.items():
    #     logger.info(f"    {key}: {value}")
    logger.info(f"Response Body: \033[35m{body}\033[0m")  # Magenta for body
