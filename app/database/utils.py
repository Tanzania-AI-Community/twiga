from time import time
import logging

logger = logging.getLogger(__name__)


# TODO: Currently not using this but might want to do something like this in the future
async def log_slow_query(query_name: str, start_time: float):
    duration = time() - start_time
    if duration > 1.0:  # Log queries taking more than 1 second
        logger.warning(f"Slow query detected: {query_name} took {duration:.2f} seconds")
