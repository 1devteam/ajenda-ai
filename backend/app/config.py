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
    cors_allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="AJENDA_CORS_ALLOWED_ORIGINS",
    )
    database_url: str = Field(
        default="postgresql+psycopg://ajenda:ajenda@db:5432/ajenda",
        alias="AJENDA_DATABASE_URL",
    )
    vector_database_url: str | None = Field(default=None, alias="AJENDA_VECTOR_DATABASE_URL")
    vector_db_enabled: bool = Field(default=True, alias="AJENDA_VECTOR_DB_ENABLED")
    vector_search_enabled: bool = Field(default=True, alias="AJENDA_VECTOR_SEARCH_ENABLED")
    vector_db_pool_size: int = Field(default=3, alias="AJENDA_VECTOR_DB_POOL_SIZE")
    vector_db_max_overflow: int = Field(default=5, alias="AJENDA_VECTOR_DB_MAX_OVERFLOW")
    ephemeral_memory_ttl_seconds: int = Field(default=86_400, alias="AJENDA_EPHEMERAL_MEMORY_TTL_SECONDS")
    db_pool_size: int = Field(default=10, alias="AJENDA_DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="AJENDA_DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="AJENDA_DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=1800, alias="AJENDA_DB_POOL_RECYCLE")
    db_idle_in_transaction_session_timeout_ms: int = Field(
        default=30_000,
        alias="AJENDA_DB_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS",
    )
    uvicorn_workers: int = Field(default=1, alias="AJENDA_UVICORN_WORKERS")
    redact_keys: str = Field(
        default="password,secret,token,api_key,authorization,cookie,set-cookie",
        alias="AJENDA_REDACT_KEYS",
    )
    queue_adapter: Literal["local", "redis"] = Field(default="local", alias="AJENDA_QUEUE_ADAPTER")
    queue_url: str | None = Field(default=None, alias="AJENDA_QUEUE_URL")
    worker_poll_interval_seconds: float = Field(default=2.0, alias="AJENDA_WORKER_POLL_INTERVAL_SECONDS")
    worker_tenant_mode: Literal["single", "multi"] = Field(default="single", alias="AJENDA_WORKER_TENANT_MODE")
    worker_tenant_refresh_seconds: float = Field(default=30.0, alias="AJENDA_WORKER_TENANT_REFRESH_SECONDS")
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
    oidc_login_enabled: bool = Field(default=False, alias="AJENDA_OIDC_LOGIN_ENABLED")
    oidc_provider: Literal["generic", "google", "auth0"] = Field(
        default="generic",
        alias="AJENDA_OIDC_PROVIDER",
    )
    oidc_client_id: str = Field(default="", alias="AJENDA_OIDC_CLIENT_ID")
    oidc_client_secret: str = Field(default="", alias="AJENDA_OIDC_CLIENT_SECRET")
    oidc_id_token_audience: str = Field(default="", alias="AJENDA_OIDC_ID_TOKEN_AUDIENCE")
    oidc_scopes: str = Field(default="openid email profile", alias="AJENDA_OIDC_SCOPES")
    oidc_redirect_uri_allowlist: str = Field(
        default="http://localhost:8080/auth/callback",
        alias="AJENDA_OIDC_REDIRECT_URI_ALLOWLIST",
    )
    oidc_login_intent_ttl_minutes: int = Field(default=10, alias="AJENDA_OIDC_LOGIN_INTENT_TTL_MINUTES")
    session_signing_secret: str = Field(default="", alias="AJENDA_SESSION_SIGNING_SECRET")
    session_access_ttl_seconds: int = Field(default=3600, alias="AJENDA_SESSION_ACCESS_TTL_SECONDS")
    session_refresh_ttl_seconds: int = Field(default=604800, alias="AJENDA_SESSION_REFRESH_TTL_SECONDS")
    auth_login_start_ip_limit_per_hour: int = Field(default=30, alias="AJENDA_AUTH_LOGIN_START_IP_LIMIT_PER_HOUR")
    auth_login_callback_ip_limit_per_hour: int = Field(
        default=30,
        alias="AJENDA_AUTH_LOGIN_CALLBACK_IP_LIMIT_PER_HOUR",
    )
    auth_login_callback_email_limit_per_hour: int = Field(
        default=20,
        alias="AJENDA_AUTH_LOGIN_CALLBACK_EMAIL_LIMIT_PER_HOUR",
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

    # --- HubSpot CRM integration ---
    hubspot_crm_adapter_public_host: str = Field(
        default="hubspot-crm-ingress",
        alias="AJENDA_HUBSPOT_CRM_ADAPTER_PUBLIC_HOST",
    )
    hubspot_platform_master_key_enabled: bool = Field(
        default=False,
        alias="AJENDA_HUBSPOT_PLATFORM_MASTER_KEY_ENABLED",
    )
    hubspot_platform_master_key: str | None = Field(
        default=None,
        alias="AJENDA_HUBSPOT_PLATFORM_MASTER_KEY",
    )
    network_egress_allow_private_destinations: bool = Field(
        default=False,
        alias="AJENDA_NETWORK_EGRESS_ALLOW_PRIVATE_DESTINATIONS",
    )
    network_egress_tls_verify: bool = Field(
        default=True,
        alias="AJENDA_NETWORK_EGRESS_TLS_VERIFY",
    )
    autonomy_disclaimer_mode: Literal["off", "pilot", "enforce"] = Field(
        default="off",
        alias="AJENDA_AUTONOMY_DISCLAIMER_MODE",
    )
    mission_intake_quality_mode: Literal["off", "enforce"] = Field(
        default="enforce",
        alias="AJENDA_MISSION_INTAKE_QUALITY_MODE",
    )
    gmail_oauth_redirect_uri: str = Field(
        default="http://localhost:5173/credentials/gmail/callback",
        alias="AJENDA_GMAIL_OAUTH_REDIRECT_URI",
    )
    linkedin_oauth_redirect_uri: str = Field(
        default="http://localhost:5173/credentials/linkedin/callback",
        alias="AJENDA_LINKEDIN_OAUTH_REDIRECT_URI",
    )
    salesforce_oauth_redirect_uri: str = Field(
        default="http://localhost:5173/credentials/salesforce/callback",
        alias="AJENDA_SALESFORCE_OAUTH_REDIRECT_URI",
    )
    google_calendar_oauth_redirect_uri: str = Field(
        default="http://localhost:5173/credentials/google-calendar/callback",
        alias="AJENDA_GOOGLE_CALENDAR_OAUTH_REDIRECT_URI",
    )
    github_oauth_redirect_uri: str = Field(
        default="http://localhost:5173/credentials/github/callback",
        alias="AJENDA_GITHUB_OAUTH_REDIRECT_URI",
    )

    # --- Billing (Stripe) ---
    STRIPE_SECRET_KEY: str = Field(default="", alias="STRIPE_SECRET_KEY")
    STRIPE_PUBLISHABLE_KEY: str = Field(default="", alias="STRIPE_PUBLISHABLE_KEY")
    STRIPE_WEBHOOK_SECRET: str = Field(default="", alias="STRIPE_WEBHOOK_SECRET")
    STRIPE_PRICE_STARTER: str = Field(default="", alias="STRIPE_PRICE_STARTER")
    STRIPE_PRICE_PRO: str = Field(default="", alias="STRIPE_PRICE_PRO")

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

    # --- Self-serve onboarding ---
    signup_enabled: bool = Field(default=True, alias="AJENDA_SIGNUP_ENABLED")
    signup_ip_limit_per_hour: int = Field(default=5, alias="AJENDA_SIGNUP_IP_LIMIT_PER_HOUR")
    signup_email_limit_per_hour: int = Field(default=3, alias="AJENDA_SIGNUP_EMAIL_LIMIT_PER_HOUR")
    signup_resend_email_limit_per_hour: int = Field(default=2, alias="AJENDA_SIGNUP_RESEND_EMAIL_LIMIT_PER_HOUR")
    signup_verify_failures_per_hour: int = Field(default=10, alias="AJENDA_SIGNUP_VERIFY_FAILURES_PER_HOUR")
    signup_bootstrap_key_ttl_hours: int = Field(default=72, alias="AJENDA_SIGNUP_BOOTSTRAP_KEY_TTL_HOURS")
    signup_verification_ttl_hours: int = Field(default=24, alias="AJENDA_SIGNUP_VERIFICATION_TTL_HOURS")
    signup_expose_verification_token: bool = Field(
        default=False,
        alias="AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN",
    )
    signup_require_idempotency_key: bool | None = Field(
        default=None,
        alias="AJENDA_SIGNUP_REQUIRE_IDEMPOTENCY_KEY",
    )
    email_provider: Literal["logging", "noop", "resend"] = Field(
        default="logging",
        alias="AJENDA_EMAIL_PROVIDER",
    )
    resend_api_key: str = Field(default="", alias="AJENDA_RESEND_API_KEY")
    email_from: str = Field(default="", alias="AJENDA_EMAIL_FROM")
    signup_verify_url_base: str = Field(default="", alias="AJENDA_SIGNUP_VERIFY_URL_BASE")
    email_delivery_timeout_seconds: float = Field(default=10.0, alias="AJENDA_EMAIL_DELIVERY_TIMEOUT_SECONDS")

    @property
    def resolved_vector_database_url(self) -> str | None:
        if not self.vector_db_enabled:
            return None
        explicit = self.vector_database_url.strip() if isinstance(self.vector_database_url, str) else ""
        return explicit or self.database_url

    @property
    def cors_allowed_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]

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

    @property
    def oidc_redirect_uri_allowlist_set(self) -> set[str]:
        return {item.strip() for item in self.oidc_redirect_uri_allowlist.split(",") if item.strip()}

    @property
    def oidc_login_ready(self) -> bool:
        return bool(
            self.oidc_login_enabled
            and str(self.oidc_client_id).strip()
            and str(self.oidc_issuer).strip()
            and str(self.session_signing_secret).strip()
        )

    @property
    def customer_session_auth_ready(self) -> bool:
        secret = str(self.session_signing_secret).strip()
        return bool(self.oidc_login_enabled and len(secret) >= 32)

    @property
    def signup_idempotency_required(self) -> bool:
        if self.signup_require_idempotency_key is not None:
            return self.signup_require_idempotency_key
        return str(self.env).strip().lower() == "production"

    @property
    def hubspot_crm_adapter_base_url(self) -> str:
        host = str(self.hubspot_crm_adapter_public_host).strip().lower().rstrip(".")
        return f"https://{host}"

    @property
    def hubspot_platform_master_ready(self) -> bool:
        return bool(
            self.hubspot_platform_master_key_enabled
            and self.hubspot_platform_master_key
            and str(self.hubspot_platform_master_key).strip()
        )

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
            if self.worker_tenant_mode == "single":
                if self.worker_tenant_id == "default" or not str(self.worker_tenant_id).strip():
                    raise ValueError("AJENDA_WORKER_TENANT_ID must be explicitly configured in production")
            elif self.worker_tenant_refresh_seconds <= 0:
                raise ValueError(
                    "AJENDA_WORKER_TENANT_REFRESH_SECONDS must be a positive number when "
                    "AJENDA_WORKER_TENANT_MODE=multi"
                )
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
            if self.hubspot_platform_master_key_enabled and not self.hubspot_platform_master_ready:
                raise ValueError(
                    "AJENDA_HUBSPOT_PLATFORM_MASTER_KEY is required when "
                    "AJENDA_HUBSPOT_PLATFORM_MASTER_KEY_ENABLED=true in production"
                )
            if self.network_egress_allow_private_destinations:
                raise ValueError("AJENDA_NETWORK_EGRESS_ALLOW_PRIVATE_DESTINATIONS is forbidden in production")
            if not self.network_egress_tls_verify:
                raise ValueError("AJENDA_NETWORK_EGRESS_TLS_VERIFY=false is forbidden in production")

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
        if self.signup_ip_limit_per_hour <= 0:
            raise ValueError(
                f"AJENDA_SIGNUP_IP_LIMIT_PER_HOUR must be a positive integer, got {self.signup_ip_limit_per_hour}"
            )
        if self.signup_email_limit_per_hour <= 0:
            raise ValueError(
                f"AJENDA_SIGNUP_EMAIL_LIMIT_PER_HOUR must be a positive integer, got {self.signup_email_limit_per_hour}"
            )
        if self.signup_resend_email_limit_per_hour <= 0:
            raise ValueError(
                "AJENDA_SIGNUP_RESEND_EMAIL_LIMIT_PER_HOUR must be a positive integer, "
                f"got {self.signup_resend_email_limit_per_hour}"
            )
        if self.signup_verify_failures_per_hour <= 0:
            raise ValueError(
                "AJENDA_SIGNUP_VERIFY_FAILURES_PER_HOUR must be a positive integer, "
                f"got {self.signup_verify_failures_per_hour}"
            )
        if self.signup_bootstrap_key_ttl_hours <= 0:
            raise ValueError(
                "AJENDA_SIGNUP_BOOTSTRAP_KEY_TTL_HOURS must be a positive integer, "
                f"got {self.signup_bootstrap_key_ttl_hours}"
            )
        if self.signup_verification_ttl_hours <= 0:
            raise ValueError(
                "AJENDA_SIGNUP_VERIFICATION_TTL_HOURS must be a positive integer, "
                f"got {self.signup_verification_ttl_hours}"
            )
        if self.email_delivery_timeout_seconds <= 0:
            raise ValueError(
                "AJENDA_EMAIL_DELIVERY_TIMEOUT_SECONDS must be a positive number, "
                f"got {self.email_delivery_timeout_seconds}"
            )
        if self.oidc_login_intent_ttl_minutes <= 0:
            raise ValueError(
                "AJENDA_OIDC_LOGIN_INTENT_TTL_MINUTES must be a positive integer, "
                f"got {self.oidc_login_intent_ttl_minutes}"
            )
        if self.session_access_ttl_seconds <= 0:
            raise ValueError(
                f"AJENDA_SESSION_ACCESS_TTL_SECONDS must be a positive integer, got {self.session_access_ttl_seconds}"
            )
        if self.session_refresh_ttl_seconds <= 0:
            raise ValueError(
                f"AJENDA_SESSION_REFRESH_TTL_SECONDS must be a positive integer, got {self.session_refresh_ttl_seconds}"
            )
        if self.auth_login_start_ip_limit_per_hour <= 0:
            raise ValueError(
                "AJENDA_AUTH_LOGIN_START_IP_LIMIT_PER_HOUR must be a positive integer, "
                f"got {self.auth_login_start_ip_limit_per_hour}"
            )
        if self.auth_login_callback_ip_limit_per_hour <= 0:
            raise ValueError(
                "AJENDA_AUTH_LOGIN_CALLBACK_IP_LIMIT_PER_HOUR must be a positive integer, "
                f"got {self.auth_login_callback_ip_limit_per_hour}"
            )
        if self.auth_login_callback_email_limit_per_hour <= 0:
            raise ValueError(
                "AJENDA_AUTH_LOGIN_CALLBACK_EMAIL_LIMIT_PER_HOUR must be a positive integer, "
                f"got {self.auth_login_callback_email_limit_per_hour}"
            )
        if self.oidc_login_enabled:
            if _blank(self.oidc_client_id):
                raise ValueError("AJENDA_OIDC_CLIENT_ID is required when AJENDA_OIDC_LOGIN_ENABLED=true")
            if _blank(self.session_signing_secret) or len(str(self.session_signing_secret).strip()) < 32:
                raise ValueError(
                    "AJENDA_SESSION_SIGNING_SECRET must be at least 32 characters when OIDC login is enabled"
                )
            if not self.oidc_redirect_uri_allowlist_set:
                raise ValueError(
                    "AJENDA_OIDC_REDIRECT_URI_ALLOWLIST must include at least one redirect URI when OIDC login is enabled"
                )
            if env == "production" and _blank(self.oidc_client_secret):
                raise ValueError(
                    "AJENDA_OIDC_CLIENT_SECRET is required in production when AJENDA_OIDC_LOGIN_ENABLED=true"
                )

        if env == "production":
            if self.email_provider == "logging":
                raise ValueError("AJENDA_EMAIL_PROVIDER=logging is forbidden in production; use resend")
            if self.email_provider == "resend":
                if _blank(self.resend_api_key):
                    raise ValueError("AJENDA_RESEND_API_KEY is required when AJENDA_EMAIL_PROVIDER=resend")
                if _blank(self.email_from):
                    raise ValueError("AJENDA_EMAIL_FROM is required when AJENDA_EMAIL_PROVIDER=resend")
                if _blank(self.signup_verify_url_base):
                    raise ValueError("AJENDA_SIGNUP_VERIFY_URL_BASE is required when AJENDA_EMAIL_PROVIDER=resend")
            if self.signup_expose_verification_token:
                raise ValueError("AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN must be false in production")
            if not self.STRIPE_SECRET_KEY or not self.STRIPE_SECRET_KEY.startswith("sk_"):
                raise ValueError(
                    "STRIPE_SECRET_KEY is required in production and must begin with 'sk_'. "
                    f"Current value: {self.STRIPE_SECRET_KEY!r}"
                )
            if not self.STRIPE_WEBHOOK_SECRET or not self.STRIPE_WEBHOOK_SECRET.startswith("whsec_"):
                raise ValueError(
                    "STRIPE_WEBHOOK_SECRET is required in production and must begin with 'whsec_'. "
                    f"Current value: {self.STRIPE_WEBHOOK_SECRET!r}"
                )
            if self.STRIPE_SECRET_KEY.startswith("sk_test_"):
                raise ValueError(
                    "STRIPE_SECRET_KEY must use live mode in production (sk_live_…). "
                    f"Current value: {self.STRIPE_SECRET_KEY!r}"
                )
            for price_env, price_value in (
                ("STRIPE_PRICE_STARTER", self.STRIPE_PRICE_STARTER),
                ("STRIPE_PRICE_PRO", self.STRIPE_PRICE_PRO),
            ):
                if _blank(price_value) or not str(price_value).startswith("price_"):
                    raise ValueError(
                        f"{price_env} is required in production and must begin with 'price_'. "
                        f"Current value: {price_value!r}"
                    )
            if self.signup_enabled:
                if _blank(self.cors_allowed_origins):
                    raise ValueError(
                        "AJENDA_CORS_ALLOWED_ORIGINS is required in production when AJENDA_SIGNUP_ENABLED=true"
                    )
                for origin in self.cors_allowed_origin_list:
                    if _is_localhost_url(origin):
                        raise ValueError(
                            "AJENDA_CORS_ALLOWED_ORIGINS must not include localhost in production. "
                            f"Current value: {self.cors_allowed_origins!r}"
                        )
                if _is_localhost_url(self.signup_verify_url_base):
                    raise ValueError(
                        "AJENDA_SIGNUP_VERIFY_URL_BASE must not point to localhost in production. "
                        f"Current value: {self.signup_verify_url_base!r}"
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
