import yaml
import os
from pathlib import Path

ASSETS_CONFIG_PATH = Path(__file__).parent.parent / "assets" / "config" # app/assets/config

def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def load_yaml_config() -> dict:
    with open(ASSETS_CONFIG_PATH / "base.yml") as f:
        config = yaml.safe_load(f)

    environment = os.getenv("ENVIRONMENT", "local")
    env_path = ASSETS_CONFIG_PATH / f"{environment}.yml"

    if env_path.exists():
        with open(env_path) as f:
            env_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, env_config)

    return config


yaml_config = load_yaml_config()
