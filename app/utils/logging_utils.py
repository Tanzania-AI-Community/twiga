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
    # Do not log credentials, response bodies, or URLs (which may be signed).
    level = logging.DEBUG if response.is_success else logging.WARNING
    logger.log(level, "WhatsApp API response: status=%s", response.status_code)
