from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "Production RAG Assistant"
    api_port: int = 8000
    database_url: str = (
        "postgresql+asyncpg://rag_assistant_dev:rag_assistant_dev@localhost:5432/"
        "rag_assistant_dev"
    )
    postgres_db: str = "rag_assistant_dev"
    postgres_user: str = "rag_assistant_dev"
    postgres_password: SecretStr = SecretStr("rag_assistant_dev")
    openai_api_key: SecretStr | None = None
    redis_url: str = "redis://localhost:6379/0"
    document_storage_path: str = "./data/documents"
    max_upload_bytes: int = 20 * 1024 * 1024
    max_docx_uncompressed_bytes: int = 100 * 1024 * 1024
    celery_max_retries: int = 3
    development_tenant_id: str | None = None
    development_user_id: str | None = None

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def normalize_optional_secret(cls, value: object) -> object:
        """Treat an empty optional secret supplied by Compose as unset."""
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
