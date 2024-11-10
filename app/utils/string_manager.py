from enum import Enum
from typing import Any, Dict
from functools import cached_property
import logging

import yaml

from app.utils.paths import paths

logger = logging.getLogger(__name__)


class StringCategory(str, Enum):
    """Categories for different types of messages"""

    ERROR = "error"
    INFO = "info"
    ONBOARDING = "onboarding"
    SYSTEM = "system"
    TOOLS = "tools"
    SETTINGS = "settings"


class StringResources:
    """Global string resources singleton"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once
        if not hasattr(self, "_strings"):
            self._load_all_strings()

    @cached_property
    def _supported_languages(self) -> list[str]:
        """Get list of supported language codes from available YAML files"""
        return [p.stem for p in paths.STRINGS.glob("*.yml")]

    def _load_all_strings(self) -> None:
        """Load all language strings at startup"""
        self._strings: Dict[str, Dict[str, Any]] = {}

        for lang_file in paths.STRINGS.glob("*.yml"):
            try:
                with open(lang_file, "r", encoding="utf-8") as f:
                    self._strings[lang_file.stem] = yaml.safe_load(f)
                logger.info(f"Loaded string resources for language: {lang_file.stem}")
            except Exception as e:
                logger.error(f"Failed to load strings from {lang_file}: {e}")
                continue

        if not self._strings:
            raise RuntimeError("No string resources could be loaded")

    def get_string(
        self, category: StringCategory, key: str, lang: str = "english"
    ) -> str:
        """Get a message by category and key"""
        try:
            return self._strings[lang][category.value][key]
        except KeyError:
            logger.error(
                f"String not found - lang: {lang}, category: {category.value}, key: {key}"
            )
            # Fallback to English error message
            return self._strings["english"]["error"]["general"]

    def get_template(
        self, category: StringCategory, key: str, lang: str = "english", **kwargs
    ) -> str:
        """Get a formatted template message"""
        try:
            template = self._strings[lang][category.value][key]
            return template.format(**kwargs)
        except (KeyError, ValueError) as e:
            logger.error(
                f"Template error - lang: {lang}, category: {category.value}, key: {key}: {e}"
            )
            return self._strings["english"]["error"]["general"]

    def get_category(
        self, category: StringCategory, lang: str = "english"
    ) -> Dict[str, str]:
        """Get all strings for a category"""
        try:
            return self._strings[lang][category.value]
        except KeyError:
            logger.error(
                f"Category not found - lang: {lang}, category: {category.value}"
            )
            return {}


# Global singleton instance
strings = StringResources()
