import logging
import httpx

logger = logging.getLogger(__name__)


async def log_httpx_response(response: httpx.Response) -> None:
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
    logger.debug(f"Response URL: {url}")
    logger.debug(f"Response Status: \033[{status_color}m{status_code}\033[0m")
    logger.debug(f"Response Body: \033[35m{body}\033[0m")  # Magenta for body
