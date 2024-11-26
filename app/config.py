"""
This module sets the env configs for our WhatsApp app.
"""

from typing import Literal, Optional
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, field_validator


# Store configurations for the app
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("TWIGA_ENV", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_nested_delimiter="__",
    )
    env_file: str = os.getenv("TWIGA_ENV", ".env")

    # Meta settings
    meta_api_version: str
    meta_app_id: str
    meta_app_secret: SecretStr

    # WhatsApp settings (TODO: Set flow stuff to optional, and add business_env)
    whatsapp_cloud_number_id: str
    whatsapp_verify_token: SecretStr
    whatsapp_api_token: SecretStr
    whatsapp_business_public_key: Optional[SecretStr] = None
    whatsapp_business_private_key: Optional[SecretStr] = None
    whatsapp_business_private_key_password: Optional[SecretStr] = None

    # Flows settings
    onboarding_flow_id: Optional[str] = None
    select_subjects_flow_id: Optional[str] = None
    select_classes_flow_id: Optional[str] = None
    flow_token_encryption_key: Optional[SecretStr] = None

    # Rate limit settings
    daily_message_limit: int

    # Database settings
    database_url: SecretStr
    migrations_url: Optional[SecretStr] = None

    # Business environment
    business_env: bool = False  # Default if not found in .env

    @field_validator("business_env", mode="before")
    @classmethod
    def parse_business_env(cls, v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "True")
        return False


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("TWIGA_ENV", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_nested_delimiter="__",
    )

    # AI provider api key
    llm_api_key: Optional[SecretStr] = None

    # Model selection
    llm_model_options: dict = {
        "llama_405b": "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
        "llama_70b": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "mixtral": "mistralai/Mixtral-8x7B-Instruct-v0.1",
        "gpt-4o": "gpt-4o",
        "gpt-4o_mini": "gpt-40-mini",
    }

    embedder_model_options: dict = {
        "bge-large": "BAAI/bge-large-en-v1.5",  # 1024 dimensions
        "text-embedding-3-small": "text-embedding-3-small",  # 1536 dimensions
    }

    """
    XXX: FILL YOUR AI PROVIDER AND MODEL CHOICES HERE (DEFAULTS ARE PREFILLED)
     - make sure your choice of LLM, embedder, and ai_provider are compatible
    """
    ai_provider: Literal["together", "openai"] = "together"
    llm_model_name: str = llm_model_options["llama_405b"]
    exercise_generator_model: str = llm_model_options["llama_70b"]
    embedding_model: str = embedder_model_options["bge-large"]


def initialize_settings():
    settings = Settings()
    llm_settings = LLMSettings()
    return settings, llm_settings


settings, llm_settings = initialize_settings()
