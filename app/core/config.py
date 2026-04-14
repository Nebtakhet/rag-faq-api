from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    ENVIRONMENT: str = "development"
    PROJECT_NAME: str = "rag-faq-api"
    API_V1_STR: str = "/api/v1"
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    admin_api_key: str = Field(default="", alias="ADMIN_API_KEY")
    max_upload_bytes: int = Field(default=5 * 1024 * 1024, alias="MAX_UPLOAD_BYTES", ge=1)
    ask_rate_limit: str = Field(default="300/minute", alias="ASK_RATE_LIMIT")
    admin_rate_limit: str = Field(default="120/minute", alias="ADMIN_RATE_LIMIT")
    rate_limit_trust_proxy_headers: bool = Field(
        default=False,
        alias="RATE_LIMIT_TRUST_PROXY_HEADERS",
    )
    rate_limit_trusted_proxy_ips: list[str] = Field(
        default_factory=list,
        alias="RATE_LIMIT_TRUSTED_PROXY_IPS",
    )
    ingestion_chunk_size: int = Field(default=1000, alias="INGESTION_CHUNK_SIZE", ge=100)
    ingestion_chunk_overlap: int = Field(default=200, alias="INGESTION_CHUNK_OVERLAP", ge=0)
    ingestion_min_alpha_ratio: float = Field(
        default=0.15,
        alias="INGESTION_MIN_ALPHA_RATIO",
        ge=0.0,
        le=1.0,
    )

    sqlalchemy_database_uri: str | None = Field(default=None, alias="SQLALCHEMY_DATABASE_URI")
    redis_url: str | None = Field(default=None, alias="REDIS_URL")

    secret_key: str | None = Field(default=None, alias="SECRET_KEY")
    refresh_token_secret: str | None = Field(default=None, alias="REFRESH_TOKEN_SECRET")
    auto_create_schema: bool | None = Field(default=None, alias="AUTO_CREATE_SCHEMA")

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def effective_sqlalchemy_database_uri(self) -> str:
        return self.sqlalchemy_database_uri or "sqlite:///./app.db"

    def validate_production_settings(self) -> None:
        if self.secret_key is not None and self.secret_key.lower() == "change-me":
            raise ValueError("SECRET_KEY must be set to a strong value")
        if (
            self.refresh_token_secret is not None
            and self.refresh_token_secret.lower() == "change-me"
        ):
            raise ValueError("REFRESH_TOKEN_SECRET must be set to a strong value")

        if not self.is_production:
            return

        if self.auto_create_schema:
            raise ValueError("AUTO_CREATE_SCHEMA must be false in production")
        if self.rate_limit_trust_proxy_headers and not self.rate_limit_trusted_proxy_ips:
            raise ValueError(
                "RATE_LIMIT_TRUSTED_PROXY_IPS must be set when RATE_LIMIT_TRUST_PROXY_HEADERS=true in production"
            )
        if self.effective_sqlalchemy_database_uri.startswith("sqlite"):
            raise ValueError("SQLALCHEMY_DATABASE_URI must not use sqlite in production")
        if not self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS must not be empty in production")

    @model_validator(mode="after")
    def _validate_settings(self) -> Self:
        self.validate_production_settings()
        return self

    def require_openai_api_key(self) -> str:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        return self.openai_api_key

    def require_admin_api_key(self) -> str:
        if not self.admin_api_key:
            raise RuntimeError("ADMIN_API_KEY is not set")
        return self.admin_api_key


settings = Settings()
