# app/core/prompts.py

from pathlib import Path
from typing import Dict
import logging
from app.utils.paths import paths

logger = logging.getLogger(__name__)


class PromptTemplate:
    def __init__(self, template: str):
        self.template = template

    def format(self, **kwargs) -> str:
        try:
            return self.template.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"Missing required parameter: {e}")
        except Exception as e:
            raise ValueError(f"Error formatting prompt: {e}")


class PromptManager:
    def __init__(self):
        self.prompts: Dict[str, PromptTemplate] = {}
        self._load_prompts()

    def _load_prompts(self) -> None:
        """Load all .txt files from the prompts directory."""
        if not paths.PROMPTS.exists():
            logger.warning(f"Prompts directory not found at {paths.PROMPTS}")
            return

        for prompt_file in paths.PROMPTS.glob("*"):
            try:
                with open(prompt_file, "r", encoding="utf-8") as f:
                    template = f.read()
                prompt_name = prompt_file.stem
                self.prompts[prompt_name] = PromptTemplate(template)
                logger.debug(f"Loaded prompt: {prompt_name}")
            except Exception as e:
                logger.error(f"Failed to load prompt {prompt_file}: {e}")

    def get_prompt(self, prompt_name: str) -> str:
        """Get raw prompt template by name."""
        if prompt_name not in self.prompts:
            raise KeyError(f"Prompt template not found: {prompt_name}")
        return self.prompts[prompt_name].template

    def format_prompt(self, prompt_name: str, **kwargs) -> str:
        """Format a prompt with the given parameters."""
        if prompt_name not in self.prompts:
            raise KeyError(f"Prompt template not found: {prompt_name}")
        return self.prompts[prompt_name].format(**kwargs)


# Initialize the global instance
prompt_manager = PromptManager()
