# app/core/paths.py

from pathlib import Path
from functools import cached_property
import os


class ProjectPaths:
    """Central management of project paths"""

    def __init__(self):
        # Go up two levels to reach app/ directory
        self.APP_ROOT = Path(__file__).parent.parent

    @cached_property
    def ASSETS(self) -> Path:
        """Assets directory containing static files"""
        return self.APP_ROOT / "assets"

    @cached_property
    def PROMPTS(self) -> Path:
        """Directory containing prompt templates"""
        return self.ASSETS / "prompts"

    @cached_property
    def STRINGS(self) -> Path:
        """Directory containing string resources"""
        return self.ASSETS / "strings"

    def __str__(self) -> str:
        """Useful for debugging path configurations"""
        return (
            f"Project Paths:\n"
            f"  APP_ROOT: {self.APP_ROOT}\n"
            f"  ASSETS: {self.ASSETS}\n"
            f"  PROMPTS: {self.PROMPTS}"
        )


# Create a singleton instance
paths = ProjectPaths()
