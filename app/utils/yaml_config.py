import os
from typing import Any

import yaml

from app.utils.paths import paths


def _deep_merge(base: dict, override: dict) -> dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_yaml_config() -> dict[str, Any]:
    with open(paths.CONFIG / "base.yml") as f:
        config = yaml.safe_load(f)

    environment = os.getenv("ENVIRONMENT", "local")
    env_path = paths.CONFIG / f"{environment}.yml"

    if env_path.exists():
        with open(env_path) as f:
            env_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, env_config)

    return config


yaml_config = load_yaml_config()
