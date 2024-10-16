"""
This module sets the env configs for our WhatsApp app.
"""

from typing import Optional
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr


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
    database_url: SecretStr


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
    return settings, llm_settings


settings, llm_settings = initialize_settings()
