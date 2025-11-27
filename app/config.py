"""
This module sets the env configs for our WhatsApp app.
"""

from typing import Literal, Optional
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, field_validator
from enum import Enum


class Environment(str, Enum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    LOCAL = "local"


# Store configurations for the app
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("TWIGA_ENV", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_nested_delimiter="__",
    )
    """ REQUIRED SETTINGS """
    # Meta settings
    meta_api_version: str
    meta_app_id: str
    meta_app_secret: SecretStr

    # WhatsApp settings
    whatsapp_cloud_number_id: str
    whatsapp_verify_token: SecretStr
    whatsapp_api_token: SecretStr

    # WhatsApp mock
    mock_whatsapp: bool = False

    # Message limiting settings
    message_character_limit: int = 65000

    # Database settings
    database_url: SecretStr

    # Business environment
    environment: Environment = Environment.LOCAL
    debug: bool = True

    # WhatsApp template message settings
    welcome_template_id: str = "twiga_registration_approved"

    @property
    def sync_database_url(self) -> str:
        return self.database_url.get_secret_value().replace("+asyncpg", "")

    """ OPTIONAL SETTINGS FOR PRODUCTION """
    # Flows settings
    onboarding_flow_id: Optional[str] = None
    subjects_classes_flow_id: Optional[str] = None
    flow_token_encryption_key: Optional[SecretStr] = None

    whatsapp_business_public_key: Optional[SecretStr] = None
    whatsapp_business_private_key: Optional[SecretStr] = None
    whatsapp_business_private_key_password: Optional[SecretStr] = None

    # Redis settings (for rate limiting)
    redis_url: Optional[SecretStr] = None
    user_message_limit: Optional[int] = None
    global_message_limit: Optional[int] = None
    time_to_live: Optional[int] = None  # In seconds (a day is 86400)

    @field_validator("debug", mode="before")
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
        "llama_3_3_70b": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "llama_4_maverick": "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
        "llama_4_scout": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
        "mixtral": "mistralai/Mixtral-8x7B-Instruct-v0.1",
        "gpt-4o": "gpt-4o",
        "gpt-4o_mini": "gpt-4o-mini",
    }

    embedder_model_options: dict = {
        "bge-large": "BAAI/bge-large-en-v1.5",  # 1024 dimensions
        "text-embedding-3-small": "text-embedding-3-small",  # 1536 dimensions
    }

    """
    XXX: FILL YOUR AI PROVIDER AND MODEL CHOICES HERE (DEFAULTS ARE PREFILLED)
     - make sure your choice of LLM, embedder, and ai_provider are compatible
    """

    ai_provider: Literal["together", "openai", "ollama"] = "ollama"
    llm_model_name: str = llm_model_options["llama_4_maverick"]
    exercise_generator_model: str = llm_model_options["llama_4_scout"]
    embedding_model: str = embedder_model_options["bge-large"]
    ollama_base_url: str = "https://0d75b3aa6374.ngrok-free.app/v1"
    ollama_model_name: Optional[str] = "llama3.2"
    ollama_embedding_model: Optional[str] = "mxbai-embed-large"
    ollama_embedding_url: Optional[str] = "https://0d75b3aa6374.ngrok-free.app"
    ollama_request_timeout: int = 30

    # LangSmith tracing settings
    langsmith_api_key: Optional[SecretStr] = None
    langsmith_project: Optional[str] = "twiga-whatsapp-chatbot"
    langsmith_tracing: bool = False
    langsmith_endpoint: Optional[str] = "https://api.smith.langchain.com"


def initialize_settings():
    settings = Settings()  # type: ignore
    llm_settings = LLMSettings()

    # Validate required Meta settings
    assert (
        settings.meta_api_version and settings.meta_api_version.strip()
    ), "META_API_VERSION is required"
    assert (
        settings.meta_app_id and settings.meta_app_id.strip()
    ), "META_APP_ID is required"
    assert (
        settings.meta_app_secret and settings.meta_app_secret.get_secret_value().strip()
    ), "META_APP_SECRET is required"

    # Validate required WhatsApp settings
    assert (
        settings.whatsapp_cloud_number_id and settings.whatsapp_cloud_number_id.strip()
    ), "WHATSAPP_CLOUD_NUMBER_ID is required"
    assert (
        settings.whatsapp_verify_token
        and settings.whatsapp_verify_token.get_secret_value().strip()
    ), "WHATSAPP_VERIFY_TOKEN is required"
    assert (
        settings.whatsapp_api_token
        and settings.whatsapp_api_token.get_secret_value().strip()
    ), "WHATSAPP_API_TOKEN is required"

    # Validate other required settings
    assert (
        settings.database_url and settings.database_url.get_secret_value().strip()
    ), "DATABASE_URL is required"

    return settings, llm_settings


settings, llm_settings = initialize_settings()
