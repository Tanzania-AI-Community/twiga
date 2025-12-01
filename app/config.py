"""
This module sets the env configs for our WhatsApp app.
"""

from typing import Optional
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr, field_validator
from enum import Enum


class Environment(str, Enum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    LOCAL = "local"


class BaseProviders(str, Enum):
    TOGETHER = "together"
    OPENAI = "openai"
    OLLAMA = "ollama"
    MODAL = "modal"


class LLMProvider(str, Enum):
    TOGETHER = BaseProviders.TOGETHER.value
    OPENAI = BaseProviders.OPENAI.value
    OLLAMA = BaseProviders.OLLAMA.value
    MODAL = BaseProviders.MODAL.value


class EmbeddingProvider(str, Enum):
    TOGETHER = BaseProviders.TOGETHER.value
    OPENAI = BaseProviders.OPENAI.value
    OLLAMA = BaseProviders.OLLAMA.value
    MODAL = BaseProviders.MODAL.value


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

    # User inactivity settings
    user_inactivity_threshold_hours: int = 24  # Hours after which user becomes inactive

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

    # LLM provider api key
    api_key: Optional[SecretStr] = Field(default=None, validation_alias="llm_api_key")

    # Model selection
    llm_options: dict = {
        "llama_405b": "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
        "llama_70b": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "llama_3_3_70b": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "llama_4_maverick": "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
        "llama_4_scout": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
        "mixtral": "mistralai/Mixtral-8x7B-Instruct-v0.1",
        "gpt-4o": "gpt-4o",
        "gpt-4o_mini": "gpt-4o-mini",
    }

    # LLM-related settings
    provider: LLMProvider = Field(
        default=LLMProvider.OLLAMA, validation_alias="llm_provider"
    )
    llm_name: str = Field(
        default=llm_options["llama_4_maverick"], validation_alias="llm_model_name"
    )
    exercise_generator_model: str = Field(
        default=llm_options["llama_4_scout"],
        validation_alias="exercise_generator_model",
    )

    ollama_base_url: str = "http://host.docker.internal:11434/v1"
    ollama_model_name: Optional[str] = "llama3.2"
    ollama_request_timeout: int = Field(
        default=30, validation_alias="ollama_llm_request_timeout"
    )

    modal_base_url: Optional[SecretStr] = None
    modal_model_name: Optional[str] = "twiga-qwen"
    modal_request_timeout: int = Field(
        default=30, validation_alias="modal_llm_request_timeout"
    )

    # LangSmith tracing settings
    langsmith_api_key: Optional[SecretStr] = None
    langsmith_project: Optional[str] = "twiga-whatsapp-chatbot"
    langsmith_tracing: bool = False
    langsmith_endpoint: Optional[str] = "https://api.smith.langchain.com"


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("TWIGA_ENV", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_nested_delimiter="__",
    )

    # Embedding provider api key
    api_key: Optional[SecretStr] = Field(
        default=None, validation_alias="embedding_api_key"
    )

    embedder_options: dict = {
        "bge-large": "BAAI/bge-large-en-v1.5",  # 1024 dimensions
        "text-embedding-3-small": "text-embedding-3-small",  # 1536 dimensions
    }

    # Embedding-related settings
    provider: EmbeddingProvider = Field(
        default=EmbeddingProvider.OLLAMA, validation_alias="embedding_provider"
    )
    embedder_name: str = Field(
        default=embedder_options["bge-large"], validation_alias="embedding_model"
    )

    ollama_model: Optional[str] = Field(
        default="mxbai-embed-large", validation_alias="ollama_embedding_model"
    )
    ollama_url: Optional[str] = Field(
        default="http://host.docker.internal:11434",
        validation_alias="ollama_embedding_url",
    )
    ollama_request_timeout: int = Field(
        default=30, validation_alias="ollama_embedding_request_timeout"
    )

    modal_model: Optional[str] = Field(
        default="mxbai-embed-large", validation_alias="modal_embedding_model"
    )
    modal_url: Optional[SecretStr] = Field(
        default=None, validation_alias="modal_embedding_url"
    )
    modal_request_timeout: int = Field(
        default=30, validation_alias="modal_embedding_request_timeout"
    )


def initialize_settings():
    settings = Settings()  # type: ignore
    llm_settings = LLMSettings()
    embedding_settings = EmbeddingSettings()

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

    return settings, llm_settings, embedding_settings


settings, llm_settings, embedding_settings = initialize_settings()
