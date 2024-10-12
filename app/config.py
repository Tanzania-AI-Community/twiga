"""
This module sets the env configs for our WhatsApp app.
"""

from typing import Optional
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr


def is_running_on_render():
    render_env = os.environ.get("RENDER") == "true"
    print(f"Is running on Render: {render_env}")
    if render_env:
        print("Environment variables:")
        print(os.environ.items())
        # for key, value in os.environ.items():
        #     if key.startswith(
        #         ("META_", "WHATSAPP_", "DAILY_", "OPENAI_", "GROQ_", "TWIGA_", ".env")
        #     ):
        #         print(
        #             f"{key}: {'*' * len(str(value))}"
        #         )  # Mask the actual values for security
    return render_env


# Store configurations for the app
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env" if os.path.exists(".env") else None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_nested_delimiter="__",
    )
    meta_api_version: str
    meta_app_id: str
    meta_app_secret: SecretStr
    whatsapp_cloud_number_id: str
    whatsapp_verify_token: SecretStr
    whatsapp_api_token: SecretStr
    daily_message_limit: int


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env" if os.path.exists(".env") else None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_nested_delimiter="__",
    )
    # OpenAI settings
    openai_api_key: Optional[SecretStr] = None
    openai_org: Optional[str] = None
    twiga_openai_assistant_id: Optional[str] = None
    # GROQ settings
    groq_api_key: Optional[SecretStr] = None


def initialize_settings():
    settings = Settings()
    llm_settings = LLMSettings()

    print("Loaded settings:")
    for field in Settings.__fields__:
        value = getattr(settings, field)
        print(f"{field}: {'*' * len(str(value))}")

    print("\nLoaded LLM settings:")
    for field in LLMSettings.__fields__:
        value = getattr(llm_settings, field)
        if value is not None:
            print(f"{field}: {'*' * len(str(value))}")
        else:
            print(f"{field}: None")

    return settings, llm_settings


is_render = is_running_on_render()
settings, llm_settings = initialize_settings()
