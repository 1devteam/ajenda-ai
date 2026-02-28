"""
Omnipath Configuration Management
Centralized configuration with environment variable support and validation.
"""

from pydantic_settings import BaseSettings
from pydantic import Field, validator
import secrets


class Settings(BaseSettings):
    """Application settings with validation."""

    # Application
    APP_NAME: str = "Omnipath"
    APP_VERSION: str = "5.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = Field(default="development", pattern="^(development|staging|production)$")

    # LLM Provider Configuration
    # API Keys
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    XAI_API_KEY: str = ""  # Grok
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Model Selection (per agent type)
    COMMANDER_PROVIDER: str = "openai"
    COMMANDER_MODEL: str = "gpt-4-turbo"
    COMMANDER_TEMPERATURE: float = 0.7

    GUARDIAN_PROVIDER: str = "anthropic"
    GUARDIAN_MODEL: str = "claude-3-5-sonnet-20241022"
    GUARDIAN_TEMPERATURE: float = 0.3  # Lower for safety

    ARCHIVIST_PROVIDER: str = "google"
    ARCHIVIST_MODEL: str = "gemini-2.0-flash-exp"
    ARCHIVIST_TEMPERATURE: float = 0.5

    FORK_PROVIDER: str = "google"
    FORK_MODEL: str = "gemini-2.0-flash-exp"
    FORK_TEMPERATURE: float = 0.7

    # Security
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    JWT_SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    API_KEY_LENGTH: int = 64

    # Database
    DATABASE_URL: str = "postgresql://omnipath:omnipath@localhost:5432/omnipath"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # Redis (Event Bus & Caching)
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 50

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_PER_HOUR: int = 1000

    # Agent System
    MAX_AGENTS_PER_TENANT: int = 100
    AGENT_EXECUTION_TIMEOUT_SECONDS: int = 300
    AGENT_MEMORY_LIMIT_MB: int = 512

    # Audit & Logging
    AUDIT_LOG_ENABLED: bool = True
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    CORS_ALLOW_CREDENTIALS: bool = True

    # Observability (v5.0)
    # OpenTelemetry
    OTEL_ENABLED: bool = True
    OTEL_SERVICE_NAME: str = "omnipath"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    OTEL_EXPORTER_OTLP_INSECURE: bool = True

    # Prometheus Metrics
    PROMETHEUS_ENABLED: bool = True
    PROMETHEUS_PORT: int = 9090
    METRICS_ENDPOINT: str = "/metrics"

    # NATS Event Bus
    NATS_ENABLED: bool = True
    NATS_URL: str = "nats://localhost:4222"
    NATS_CLUSTER_ID: str = "omnipath-cluster"
    NATS_CLIENT_ID: str = "omnipath-backend"
    NATS_MAX_RECONNECT_ATTEMPTS: int = 10

    # Jaeger (for trace visualization)
    JAEGER_AGENT_HOST: str = "localhost"
    JAEGER_AGENT_PORT: int = 6831

    @validator("ENVIRONMENT")
    def validate_environment(cls, v):
        """Ensure environment is valid."""
        if v not in ["development", "staging", "production"]:
            raise ValueError("Invalid environment")
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"  # Ignore unknown environment variables


# Global settings instance
settings = Settings()
