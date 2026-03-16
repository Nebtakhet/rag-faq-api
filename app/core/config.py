from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    admin_api_key: str = Field(default="", alias="ADMIN_API_KEY")
    max_upload_bytes: int = Field(default=5 * 1024 * 1024, alias="MAX_UPLOAD_BYTES", ge=1)

    sqlalchemy_database_uri: str | None = Field(default=None, alias="SQLALCHEMY_DATABASE_URI")
    redis_url: str | None = Field(default=None, alias="REDIS_URL")

    secret_key: str | None = Field(default=None, alias="SECRET_KEY")
    refresh_token_secret: str | None = Field(default=None, alias="REFRESH_TOKEN_SECRET")
    auto_create_schema: bool | None = Field(default=None, alias="AUTO_CREATE_SCHEMA")

    def require_openai_api_key(self) -> str:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        return self.openai_api_key

    def require_admin_api_key(self) -> str:
        if not self.admin_api_key:
            raise RuntimeError("ADMIN_API_KEY is not set")
        return self.admin_api_key


settings = Settings()
