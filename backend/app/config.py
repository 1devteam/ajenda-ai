from __future__ import annotations

import base64
import binascii
import math
import os
import socket
from functools import lru_cache
from typing import Literal

from cryptography.fernet import Fernet
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
    # Dynamic worker identity: prefer POD_NAME (K8s), fall back to hostname+pid
    worker_identity: str = Field(
        default_factory=lambda: os.getenv("POD_NAME") or f"{socket.gethostname()}-{os.getpid()}",
        alias="AJENDA_WORKER_IDENTITY",
    )
    worker_tenant_id: str = Field(default="default", alias="AJENDA_WORKER_TENANT_ID")

    # OIDC / JWT Verification
    # Required in production. Defaults allow local dev without an IdP.
    oidc_jwks_uri: str = Field(
        default="http://localhost:8080/realms/ajenda/protocol/openid-connect/certs",
        alias="AJENDA_OIDC_JWKS_URI",
    )
    oidc_issuer: str = Field(
        default="http://localhost:8080/realms/ajenda",
        alias="AJENDA_OIDC_ISSUER",
    )
    oidc_audience: str = Field(
        default="ajenda-api",
        alias="AJENDA_OIDC_AUDIENCE",
    )

    # Rate limiting
    rate_limit_requests: int = Field(default=100, alias="AJENDA_RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: int = Field(default=60, alias="AJENDA_RATE_LIMIT_WINDOW_SECONDS")
    authz_policy_mode: Literal["rbac", "shadow_opa", "enforce_opa"] = Field(
        default="rbac",
        alias="AJENDA_AUTHZ_POLICY_MODE",
    )
    authz_opa_url: str | None = Field(default=None, alias="AJENDA_AUTHZ_OPA_URL")
    authz_opa_timeout_seconds: float = Field(default=2.0, alias="AJENDA_AUTHZ_OPA_TIMEOUT_SECONDS")
    webhook_secret_encryption_key: str | None = Field(
        default=None,
        alias="AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY",
    )
    webhook_secret_encryption_key_prev: str | None = Field(
        default=None,
        alias="AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY_PREV",
    )
    runtime_secret_encryption_key: str | None = Field(
        default=None,
        alias="AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY",
    )
    runtime_secret_encryption_key_prev: str | None = Field(
        default=None,
        alias="AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY_PREV",
    )

    budget_policy_enabled: bool = Field(default=False, alias="AJENDA_BUDGET_POLICY_ENABLED")
    budget_policy_observe_only: bool = Field(default=True, alias="AJENDA_BUDGET_POLICY_OBSERVE_ONLY")
    budget_policy_enforce: bool = Field(default=False, alias="AJENDA_BUDGET_POLICY_ENFORCE")
    budget_policy_enforce_tenant_ids: str = Field(default="", alias="AJENDA_BUDGET_POLICY_ENFORCE_TENANT_IDS")
    budget_policy_enforce_plans: str = Field(default="", alias="AJENDA_BUDGET_POLICY_ENFORCE_PLANS")

    lifecycle_policy_enforce_retention_class: bool = Field(
        default=False, alias="AJENDA_LIFECYCLE_POLICY_ENFORCE_RETENTION_CLASS"
    )
    lifecycle_policy_enforce_escalation_transitions: bool = Field(
        default=False, alias="AJENDA_LIFECYCLE_POLICY_ENFORCE_ESCALATION_TRANSITIONS"
    )
    lifecycle_policy_enforce_provenance_confidence_floor: bool = Field(
        default=False, alias="AJENDA_LIFECYCLE_POLICY_ENFORCE_PROVENANCE_CONFIDENCE_FLOOR"
    )
    lifecycle_policy_provenance_confidence_floor: float = Field(
        default=0.75, alias="AJENDA_LIFECYCLE_POLICY_PROVENANCE_CONFIDENCE_FLOOR"
    )

    @property
    def redact_key_set(self) -> set[str]:
        return {item.strip().lower() for item in self.redact_keys.split(",") if item.strip()}

    @staticmethod
    def _csv_set(value: str) -> set[str]:
        return {item.strip().lower() for item in value.split(",") if item.strip()}

    @property
    def budget_policy_enforce_tenant_id_set(self) -> set[str]:
        return self._csv_set(self.budget_policy_enforce_tenant_ids)

    @property
    def budget_policy_enforce_plan_set(self) -> set[str]:
        return self._csv_set(self.budget_policy_enforce_plans)

    def validate_runtime_contract(self) -> None:
        """Validate production/runtime safety configuration.

        This method is intentionally called explicitly by app startup and tests,
        including tests that construct Settings via model_construct().
        """
        env = str(self.env).strip().lower()

        def _blank(value: object) -> bool:
            return value is None or not str(value).strip()

        def _is_localhost_url(value: str) -> bool:
            lowered = value.lower()
            return (
                "://localhost" in lowered
                or "://127.0.0.1" in lowered
                or "://0.0.0.0" in lowered
                or "://[::1]" in lowered
            )

        def _validate_fernet_key(*, value: str | None, env_name: str, required: bool) -> None:
            if _blank(value):
                if required:
                    raise ValueError(f"{env_name} is required in production")
                return

            assert value is not None
            if value != value.strip() or any(char.isspace() for char in value):
                raise ValueError(
                    f"{env_name} must not contain surrounding or embedded whitespace. Current value: {value!r}"
                )

            try:
                decoded = base64.urlsafe_b64decode(value.encode("ascii"))
                recoded = base64.urlsafe_b64encode(decoded).decode("ascii")
            except Exception as exc:
                raise ValueError(f"{env_name} must be a valid Fernet key. Current value: {value!r}") from exc

            if recoded != value:
                raise ValueError(f"{env_name} must be canonical URL-safe base64. Current value: {value!r}")

            if len(decoded) != 32:
                raise ValueError(f"{env_name} must be a valid Fernet key. Current value: {value!r}")

            deterministic_test_key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
            if value == deterministic_test_key:
                raise ValueError(f"{env_name} must not use the deterministic development/test key")

        if self.queue_adapter == "redis" and _blank(self.queue_url):
            raise ValueError(
                f"AJENDA_QUEUE_URL is required when AJENDA_QUEUE_ADAPTER=redis. Current value: {self.queue_url!r}"
            )

        if env == "production" and self.queue_adapter == "local":
            raise ValueError(
                "AJENDA_QUEUE_ADAPTER=local is forbidden in production; use redis or another durable adapter"
            )

        if env == "production":
            if _is_localhost_url(str(self.oidc_jwks_uri)):
                raise ValueError(
                    "AJENDA_OIDC_JWKS_URI must not point to localhost in production. "
                    f"Current value: {self.oidc_jwks_uri!r}. Use the production IdP JWKS URL."
                )
            if _is_localhost_url(str(self.oidc_issuer)):
                raise ValueError(
                    "AJENDA_OIDC_ISSUER must not point to localhost in production. "
                    f"Current value: {self.oidc_issuer!r}. Use the production IdP issuer URL."
                )
            if self.worker_tenant_id == "default" or not str(self.worker_tenant_id).strip():
                raise ValueError("AJENDA_WORKER_TENANT_ID must be explicitly configured in production")
            _validate_fernet_key(
                value=self.webhook_secret_encryption_key,
                env_name="AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY",
                required=True,
            )
            _validate_fernet_key(
                value=self.runtime_secret_encryption_key,
                env_name="AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY",
                required=True,
            )

        if self.webhook_secret_encryption_key_prev is not None and str(self.webhook_secret_encryption_key_prev).strip():
            _validate_fernet_key(
                value=self.webhook_secret_encryption_key_prev,
                env_name="AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY_PREV",
                required=False,
            )
        if self.runtime_secret_encryption_key_prev is not None and str(self.runtime_secret_encryption_key_prev).strip():
            _validate_fernet_key(
                value=self.runtime_secret_encryption_key_prev,
                env_name="AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY_PREV",
                required=False,
            )

        if self.rate_limit_requests <= 0:
            raise ValueError(f"AJENDA_RATE_LIMIT_REQUESTS must be a positive integer, got {self.rate_limit_requests}")
        if self.rate_limit_window_seconds <= 0:
            raise ValueError(
                f"AJENDA_RATE_LIMIT_WINDOW_SECONDS must be a positive integer, got {self.rate_limit_window_seconds}"
            )

        if self.authz_policy_mode in {"shadow_opa", "enforce_opa"}:
            if _blank(self.authz_opa_url):
                raise ValueError(
                    f"AJENDA_AUTHZ_OPA_URL is required when AJENDA_AUTHZ_POLICY_MODE={self.authz_policy_mode}"
                )
        if (
            math.isnan(self.lifecycle_policy_provenance_confidence_floor)
            or self.lifecycle_policy_provenance_confidence_floor < 0
            or self.lifecycle_policy_provenance_confidence_floor > 1
        ):
            raise ValueError("AJENDA_LIFECYCLE_POLICY_PROVENANCE_CONFIDENCE_FLOOR must be between 0 and 1")

        if self.authz_opa_timeout_seconds <= 0:
            raise ValueError(
                f"AJENDA_AUTHZ_OPA_TIMEOUT_SECONDS must be a positive number, got {self.authz_opa_timeout_seconds}"
            )
        if self.budget_policy_enforce and not self.budget_policy_enabled:
            raise ValueError("AJENDA_BUDGET_POLICY_ENFORCE requires AJENDA_BUDGET_POLICY_ENABLED=true")

        if self.budget_policy_enforce and self.budget_policy_observe_only:
            raise ValueError("AJENDA_BUDGET_POLICY_OBSERVE_ONLY must be false when AJENDA_BUDGET_POLICY_ENFORCE=true")
        if self.budget_policy_enforce and not (
            self.budget_policy_enforce_tenant_id_set or self.budget_policy_enforce_plan_set
        ):
            raise ValueError("AJENDA_BUDGET_POLICY_ENFORCE requires at least one opted-in tenant or plan")
        if not self.budget_policy_enabled and not self.budget_policy_observe_only:
            raise ValueError("AJENDA_BUDGET_POLICY_OBSERVE_ONLY must be true when AJENDA_BUDGET_POLICY_ENABLED=false")

    @staticmethod
    def _validate_required_fernet_key(*, value: str | None, env_name: str) -> None:
        if value is None or not value.strip():
            raise ValueError(f"{env_name} is required in production")
        Settings._validate_optional_fernet_key(value=value, env_name=env_name)

    @staticmethod
    def _validate_optional_fernet_key(*, value: str, env_name: str) -> None:
        normalized_value = value.strip()
        if normalized_value != value or any(character.isspace() for character in value):
            raise ValueError(f"{env_name} must not contain surrounding or embedded whitespace")

        try:
            decoded_key = base64.urlsafe_b64decode(normalized_value.encode())
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"{env_name} must be a valid Fernet key") from exc

        canonical_value = base64.urlsafe_b64encode(decoded_key).decode()
        if canonical_value != normalized_value:
            raise ValueError(f"{env_name} must be canonical URL-safe base64")

        if decoded_key == b"\x00" * 32:
            raise ValueError(f"{env_name} must not use the deterministic development/test key")

        try:
            Fernet(normalized_value.encode())
        except Exception as exc:
            raise ValueError(f"{env_name} must be a valid Fernet key") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime_contract()
    return settings
