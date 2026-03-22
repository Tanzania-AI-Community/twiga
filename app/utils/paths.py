# app/core/paths.py

from functools import cached_property
from pathlib import Path


class ProjectPaths:
    """Central management of project paths"""

    def __init__(self):
        # Go up two levels to reach app/ directory
        self.APP_ROOT = Path(__file__).parent.parent

    @cached_property
    def REPO_ROOT(self) -> Path:
        """Repository root directory."""
        return self.APP_ROOT.parent

    @cached_property
    def ASSETS(self) -> Path:
        """Assets directory containing static files"""
        return self.APP_ROOT / "assets"

    @cached_property
    def EXAM_PDF_OUTPUT_DIR(self) -> Path:
        """Directory where rendered exam PDFs are stored."""
        return self.REPO_ROOT / "outputs" / "exam_pdfs"

    @cached_property
    def EXAM_GENERATOR_TEMPLATE_DIR(self) -> Path:
        """Directory containing exam generator JSON templates."""
        return (
            self.APP_ROOT
            / "tools"
            / "tool_code"
            / "generate_necta_style_exam"
            / "template"
        )

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
            f"  REPO_ROOT: {self.REPO_ROOT}\n"
            f"  ASSETS: {self.ASSETS}\n"
            f"  PROMPTS: {self.PROMPTS}"
        )


# Create a singleton instance
paths = ProjectPaths()
