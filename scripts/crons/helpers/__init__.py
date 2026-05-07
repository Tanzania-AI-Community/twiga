"""
Helper modules for cron jobs.

This package contains shared utilities and helpers for cron job scripts,
making them more maintainable and testable.
"""

from app.database.db import (
    create_new_message as create_message,
    get_users_by_state,
    get_users_to_mark_inactive,
    update_user,
)
from app.database.engine import get_session
from app.database.utils import get_database_url

from .logging import setup_logging
from .whatsapp import WhatsAppClient

__all__ = [
    "get_database_url",
    "get_session",
    "get_users_by_state",
    "get_users_to_mark_inactive",
    "update_user",
    "create_message",
    "WhatsAppClient",
    "setup_logging",
]
