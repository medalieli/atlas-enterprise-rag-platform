from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
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
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    embedding_batch_size: int = Field(default=64, ge=1, le=2048)
    embedding_request_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    embedding_provider_max_retries: int = Field(default=0, ge=0, le=2)
    embedding_max_input_tokens: int = Field(default=8191, ge=1, le=8192)
    embedding_max_batch_tokens: int = Field(default=300_000, ge=1, le=300_000)
    reranker_model_id: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    reranker_model_revision: str = "1427fd652930e4ba29e8149678df786c240d8825"
    reranker_model_path: str = "/models/reranker"
    reranker_candidate_limit: int = Field(default=30, ge=1, le=200)
    reranker_batch_size: int = Field(default=8, ge=1, le=64)
    reranker_max_length: int = Field(default=512, ge=32, le=1024)
    reranker_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    reranker_max_concurrency: int = Field(default=2, ge=1, le=8)
    answer_model: str = "gpt-5.6-terra"
    answer_reasoning_effort: str = "low"
    answer_verbosity: str = "medium"
    answer_max_context_chunks: int = Field(default=8, ge=1, le=20)
    answer_max_context_tokens: int = Field(default=12_000, ge=256, le=100_000)
    answer_max_context_chars: int = Field(default=48_000, ge=1_024, le=400_000)
    answer_max_output_tokens: int = Field(default=2_000, ge=128, le=16_000)
    answer_provider_timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    answer_provider_max_retries: int = Field(default=1, ge=0, le=1)
    answer_max_concurrency: int = Field(default=2, ge=1, le=8)
    answer_max_claims: int = Field(default=12, ge=1, le=30)
    answer_max_citations_per_claim: int = Field(default=5, ge=1, le=10)
    redis_url: str = "redis://localhost:6379/0"
    document_storage_path: str = "./data/documents"
    max_upload_bytes: int = 20 * 1024 * 1024
    max_docx_uncompressed_bytes: int = 100 * 1024 * 1024
    celery_max_retries: int = 3
    parser_max_pdf_pages: int = 500
    parser_max_extracted_chars: int = 5_000_000
    parser_max_pdf_stream_bytes: int = 50 * 1024 * 1024
    parser_soft_time_limit_seconds: int = 120
    parser_hard_time_limit_seconds: int = 150
    chunk_target_chars: int = 1200
    chunk_max_chars: int = 1800
    chunk_overlap_chars: int = 150
    development_tenant_id: str | None = None
    development_user_id: str | None = None

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def normalize_optional_secret(cls, value: object) -> object:
        """Treat an empty optional secret supplied by Compose as unset."""
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_parsing_limits(self) -> "Settings":
        positive = (
            self.parser_max_pdf_pages,
            self.parser_max_extracted_chars,
            self.parser_max_pdf_stream_bytes,
            self.parser_soft_time_limit_seconds,
            self.parser_hard_time_limit_seconds,
            self.chunk_target_chars,
            self.chunk_max_chars,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("Parsing and chunking limits must be positive")
        if self.parser_hard_time_limit_seconds <= self.parser_soft_time_limit_seconds:
            raise ValueError("Parser hard time limit must exceed its soft time limit")
        if self.chunk_target_chars > self.chunk_max_chars:
            raise ValueError("Chunk target cannot exceed chunk maximum")
        if not 0 <= self.chunk_overlap_chars < self.chunk_target_chars:
            raise ValueError("Chunk overlap must be smaller than chunk target")
        if self.embedding_provider != "openai":
            raise ValueError("Production embedding provider must be 'openai'")
        if self.embedding_dimensions != 1536:
            raise ValueError("Database schema requires 1536 embedding dimensions")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
