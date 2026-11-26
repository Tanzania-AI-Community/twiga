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


# Meta's documented error fields; raw bodies can echo user data
META_ERROR_FIELDS = ("message", "type", "code", "error_subcode", "fbtrace_id")


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
    log_method(f"Response URL: {url.copy_with(query=None, userinfo=b'')}")
    log_method(f"Response Status: \033[{status_color}m{status_code}\033[0m")

    if status_code >= 400:
        try:
            error = response.json()["error"]
            details = {key: error[key] for key in META_ERROR_FIELDS if key in error}
        except (ValueError, KeyError, TypeError):
            details = "unavailable"
        log_method(f"Response Error: {details or 'unavailable'}")
