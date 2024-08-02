from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr


# Store whatsapp configurations for the app (TODO: Add OpenAI and Groq configurations)
class Settings(BaseSettings):
    # Load configurations from .env file
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_file_encoding="utf-8"
    )

    meta_api_version: str
    meta_app_id: str
    meta_app_secret: SecretStr
    whatsapp_cloud_number_id: str
    whatsapp_verify_token: SecretStr
    whatsapp_api_token: SecretStr


settings = Settings()
