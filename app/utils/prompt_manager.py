# app/core/prompts.py

import logging

import yaml

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
        self._prompts: dict[tuple[str, str], PromptTemplate] = {}
        self._active_versions: dict[str, str] = {}
        self._load_prompts_from_registry()

    def _load_prompts_from_registry(self) -> None:
        """Load prompt templates from the registry (prompts.yml) and the prompts directory."""
        if not paths.PROMPT_REGISTRY.exists():
            raise FileNotFoundError(
                f"Prompt registry not found at {paths.PROMPT_REGISTRY}"
            )

        with open(paths.PROMPT_REGISTRY, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        registry: dict = data.get("prompts") or {}

        if not registry:
            raise ValueError("No prompts found in registry.")

        for name, config in registry.items():
            active_version: str = config["active_version"]
            versions: dict = config.get("versions") or {}

            if active_version not in versions:
                raise ValueError(
                    f"Active version '{active_version}' for prompt '{name}' is not declared in versions."
                )
            self._active_versions[name] = active_version

            # Load every version listed under "versions:" so eval/test code can
            # use explicit overrides without touching YAML.
            for version in versions:
                prompt_path = paths.PROMPTS / name / version
                if not prompt_path.exists():
                    raise FileNotFoundError(
                        f"Prompt file missing for '{name}' version '{version}': {prompt_path}"
                    )
                with open(prompt_path, encoding="utf-8") as f:
                    template_text = f.read()
                self._prompts[(name, version)] = PromptTemplate(template_text)
                logger.debug(f"Loaded prompt '{name}' version '{version}'")

    def get_active_prompt(self, name: str) -> str:
        """Get the raw template text for the active version of a prompt."""
        version = self.get_active_version(name)
        return self._prompts[(name, version)].template

    def get_active_version(self, name: str) -> str:
        """Return the active version label for a prompt (e.g. 'v0.0')."""
        if name not in self._active_versions:
            raise KeyError(f"Prompt '{name}' not found in registry.")
        return self._active_versions[name]

    def format_prompt(
        self,
        name: str,
        *,
        version: str | None = None,
        **kwargs,
    ) -> str:
        """Format a prompt with the given parameters."""
        resolved_version = (
            version if version is not None else self.get_active_version(name)
        )
        key = (name, resolved_version)
        if key not in self._prompts:
            raise KeyError(
                f"Prompt '{name}' version '{resolved_version}' not loaded. "
                f"Known versions: {[v for n, v in self._prompts if n == name]}"
            )
        return self._prompts[key].format(**kwargs)


# Initialize the global instance
prompt_manager = PromptManager()
