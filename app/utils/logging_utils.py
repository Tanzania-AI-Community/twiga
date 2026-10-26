import logging
from contextlib import contextmanager
from contextvars import ContextVar

import httpx

logger = logging.getLogger(__name__)
_private_media = ContextVar("private_media", default=False)


class _MediaLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # SDK debug logs can contain base64, signed URLs, or authorization headers.
        sdk = record.name.split(".")[0] in {
            "httpx",
            "httpcore",
            "openai",
            "langchain",
            "langchain_core",
            "langsmith",
        }
        return not (_private_media.get() and sdk)


@contextmanager
def private_media_logging():
    """Suppress payload-bearing SDK logs only in this asynchronous context."""
    # Filter handlers, not just known loggers: SDKs may create child loggers lazily.
    loggers = [logging.getLogger(), *logging.Logger.manager.loggerDict.values()]
    for target in loggers:
        if isinstance(target, logging.Logger):
            for handler in target.handlers:
                if not any(isinstance(f, _MediaLogFilter) for f in handler.filters):
                    handler.addFilter(_MediaLogFilter())
    token = _private_media.set(True)
    try:
        yield
    finally:
        _private_media.reset(token)


def log_httpx_response(response: httpx.Response) -> None:
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
        log_method = logger.debug
    elif 300 <= status_code < 400:
        status_color = ANSI_COLOR_CODES["cyan"]
        log_method = logger.info
    elif 400 <= status_code < 500:
        status_color = ANSI_COLOR_CODES["yellow"]
        log_method = logger.warning
    else:
        status_color = ANSI_COLOR_CODES["red"]
        log_method = logger.error
    from app.config import settings

    if log_method != logger.info:
        log_method(f"Current app ID: {settings.meta_app_id}")
        log_method(f"Current api version: {settings.meta_api_version}")
        log_method(f"Current cloud number ID: {settings.whatsapp_cloud_number_id}")
        log_method(
            f"Current whatsapp api token: {settings.whatsapp_api_token.get_secret_value()}"
        )
        log_method(f"Current app secret: {settings.meta_app_secret.get_secret_value()}")
    log_method(f"Response URL: {url}")
    log_method(f"Response Status: \033[{status_color}m{status_code}\033[0m")
    log_method(f"Response Body: \033[35m{body}\033[0m")
