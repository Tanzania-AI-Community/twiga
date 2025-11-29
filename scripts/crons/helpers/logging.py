"""
Logging helper for cron jobs.

Provides consistent logging configuration across all cron jobs.
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    name: str,
    log_file: Optional[str] = None,
    level: int = logging.INFO,
    format_string: Optional[str] = None,
) -> logging.Logger:
    """
    Set up logging for a cron job.

    Args:
        name: Name of the logger (usually the cron job name)
        log_file: Path to log file (optional)
        level: Logging level (default: INFO)
        format_string: Custom format string (optional)

    Returns:
        logging.Logger: Configured logger
    """
    if format_string is None:
        format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        # Ensure log directory exists
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, mode="a"))

    logging.basicConfig(
        level=level,
        format=format_string,
        handlers=handlers,
    )

    logger = logging.getLogger(name)
    return logger


def log_job_start(logger: logging.Logger, job_name: str, **config):
    """
    Log the start of a cron job with configuration.

    Args:
        logger: Logger instance
        job_name: Name of the cron job
        **config: Configuration parameters to log
    """
    logger.info(f"Starting {job_name}")
    if config:
        logger.info(f"Configuration: {config}")


def log_job_completion(
    logger: logging.Logger,
    job_name: str,
    success_count: int,
    error_count: int,
):
    """
    Log the completion of a cron job with statistics.

    Args:
        logger: Logger instance
        job_name: Name of the cron job
        success_count: Number of successful operations
        error_count: Number of failed operations
    """
    logger.info(
        f"{job_name} completed. Success: {success_count}, Errors: {error_count}"
    )

    if error_count > 0:
        logger.warning(f"Job completed with {error_count} errors")


def log_processing_item(logger: logging.Logger, item_type: str, item_id: str):
    """
    Log processing of an individual item.

    Args:
        logger: Logger instance
        item_type: Type of item being processed (e.g., "user")
        item_id: Identifier of the item
    """
    logger.info(f"Processing {item_type}: {item_id}")


def log_item_success(logger: logging.Logger, item_type: str, item_id: str, action: str):
    """
    Log successful processing of an item.

    Args:
        logger: Logger instance
        item_type: Type of item processed
        item_id: Identifier of the item
        action: Action that was performed
    """
    logger.info(f"Successfully {action} {item_type} {item_id}")


def log_item_error(
    logger: logging.Logger,
    item_type: str,
    item_id: str,
    action: str,
    error: Exception,
):
    """
    Log error processing an item.

    Args:
        logger: Logger instance
        item_type: Type of item
        item_id: Identifier of the item
        action: Action that failed
        error: Exception that occurred
    """
    logger.error(f"Failed to {action} {item_type} {item_id}: {str(error)}")
