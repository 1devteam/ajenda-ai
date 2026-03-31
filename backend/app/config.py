from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the Ajenda API process."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Ajenda AI", alias="AJENDA_APP_NAME")
    env: Literal["development", "test", "staging", "production"] = Field(
        default="development",
        alias="AJENDA_ENV",
    )
    log_level: str = Field(default="INFO", alias="AJENDA_LOG_LEVEL")
    log_json: bool = Field(default=False, alias="AJENDA_LOG_JSON")
    host: str = Field(default="0.0.0.0", alias="AJENDA_HOST")
    port: int = Field(default=8000, alias="AJENDA_PORT")
    database_url: str = Field(
        default="postgresql+psycopg://ajenda:ajenda@db:5432/ajenda",
        alias="AJENDA_DATABASE_URL",
    )
    db_pool_size: int = Field(default=10, alias="AJENDA_DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="AJENDA_DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="AJENDA_DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=1800, alias="AJENDA_DB_POOL_RECYCLE")
    redact_keys: str = Field(
        default="password,secret,token,api_key,authorization,cookie,set-cookie",
        alias="AJENDA_REDACT_KEYS",
    )
    queue_adapter: Literal["local", "redis"] = Field(default="local", alias="AJENDA_QUEUE_ADAPTER")
    queue_url: str | None = Field(default=None, alias="AJENDA_QUEUE_URL")
    worker_poll_interval_seconds: float = Field(default=2.0, alias="AJENDA_WORKER_POLL_INTERVAL_SECONDS")
    worker_identity: str = Field(default="worker-1", alias="AJENDA_WORKER_IDENTITY")
    worker_tenant_id: str = Field(default="default", alias="AJENDA_WORKER_TENANT_ID")

    @property
    def redact_key_set(self) -> set[str]:
        return {item.strip().lower() for item in self.redact_keys.split(",") if item.strip()}

    def validate_runtime_contract(self) -> None:
        if self.queue_adapter == "redis" and (self.queue_url is None or not self.queue_url.strip()):
            raise ValueError("AJENDA_QUEUE_URL is required when AJENDA_QUEUE_ADAPTER=redis")
        if self.env == "production" and self.queue_adapter == "local":
            raise ValueError("AJENDA_QUEUE_ADAPTER=local is forbidden in production")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime_contract()
    return settings
