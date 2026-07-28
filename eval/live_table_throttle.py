import time
from typing import Any


class LiveTableThrottle:
    """Throttle Streamlit live table redraws so rerenders don't flood the UI."""

    def __init__(self, min_interval_s: float = 1.0) -> None:
        self._min_interval = min_interval_s
        self._last_render = 0.0
        self._placeholder: Any = None

    def set_placeholder(self, placeholder: Any) -> None:
        self._placeholder = placeholder

    def update(self, df: Any, force: bool = False) -> bool:
        """Update the table if enough time has passed or force=True.
        Returns True if the table was redrawn."""
        now = time.monotonic()
        if force or (now - self._last_render) >= self._min_interval:
            if self._placeholder is not None:
                self._placeholder.dataframe(df, use_container_width=True)
            self._last_render = now
            return True
        return False
