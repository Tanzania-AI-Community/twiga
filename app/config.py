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
        env_file=os.getenv("TWIGA_ENV", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_nested_delimiter="__",
    )
    # Meta settings
    meta_api_version: str
    meta_app_id: str
    meta_app_secret: SecretStr
    whatsapp_cloud_number_id: str
    whatsapp_verify_token: SecretStr
    whatsapp_api_token: SecretStr
    # Rate limit settings
    daily_message_limit: int
    # Database settings
    database_url: SecretStr
    migrations_url: Optional[SecretStr] = None
    # Debug settings
    debug: bool = False


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("TWIGA_ENV", ".env"),
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
    # Together AI settings
    together_api_key: Optional[SecretStr] = None
    # Model selection
    llm_model_options: dict = {
        "llama_405b": "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
        "llama_70b": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "mixtral": "mistralai/Mixtral-8x7B-Instruct-v0.1",
    }
    llm_model_name: str = llm_model_options["llama_70b"]


def initialize_settings():
    settings = Settings()
    llm_settings = LLMSettings()
    return settings, llm_settings


settings, llm_settings = initialize_settings()
