"""
This module sets the env configs for our WhatsApp app.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr


# Store configurations for the app
class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_file_encoding="utf-8"
    )  # Load configurations from .env file

    meta_api_version: str
    meta_app_id: str
    meta_app_secret: SecretStr
    whatsapp_cloud_number_id: str
    whatsapp_verify_token: SecretStr
    whatsapp_api_token: SecretStr
    daily_message_limit: int


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_file_encoding="utf-8"
    )  # Load configurations from .env file

    # OpenAI settings
    openai_api_key: SecretStr
    openai_org: str
    twiga_openai_assistant_id: str

    # GROQ settings
    groq_api_key: SecretStr


settings = Settings()
llm_settings = LLMSettings()
