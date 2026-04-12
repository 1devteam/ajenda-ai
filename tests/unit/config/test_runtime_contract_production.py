"""Unit tests for the production runtime contract validation in Settings.

Verifies that validate_runtime_contract() raises ValueError for configurations
that are insecure or non-functional in production:

  1. Redis queue URL required when adapter=redis (existing)
  2. Local queue adapter forbidden in production (existing)
  3. OIDC JWKS URI must not point to localhost in production (new)
  4. OIDC issuer must not point to localhost in production (new)
  5. Rate limit parameters must be positive (new)

Also verifies that valid configurations pass without raising.
"""

from __future__ import annotations

import pytest

from backend.app.config import Settings


def _settings(**overrides) -> Settings:
    """Build a Settings instance via model_construct (no env-var resolution)."""
    defaults = {
        "app_name": "Ajenda AI",
        "env": "production",
        "log_level": "INFO",
        "log_json": True,
        "host": "0.0.0.0",
        "port": 8000,
        "database_url": "postgresql+psycopg://ajenda:ajenda@db:5432/ajenda",
        "db_pool_size": 10,
        "db_max_overflow": 20,
        "db_pool_timeout": 30,
        "db_pool_recycle": 1800,
        "redact_keys": "password,secret",
        "queue_adapter": "redis",
        "queue_url": "redis://redis:6379/0",
        "worker_poll_interval_seconds": 2.0,
        "worker_identity": "worker-1",
        "worker_tenant_id": "default",
        "oidc_jwks_uri": "https://idp.example.com/realms/ajenda/protocol/openid-connect/certs",
        "oidc_issuer": "https://idp.example.com/realms/ajenda",
        "oidc_audience": "ajenda-api",
        "rate_limit_requests": 100,
        "rate_limit_window_seconds": 60,
        "authz_policy_mode": "rbac",
        "authz_opa_url": None,
        "authz_opa_timeout_seconds": 2.0,
    }
    defaults.update(overrides)
    return Settings.model_construct(**defaults)


# ---------------------------------------------------------------------------
# Valid production configuration — must not raise
# ---------------------------------------------------------------------------


class TestValidProductionConfig:
    def test_valid_production_config_passes(self) -> None:
        """A fully-configured production environment must not raise."""
        settings = _settings()
        settings.validate_runtime_contract()  # Must not raise

    def test_staging_with_localhost_oidc_is_allowed(self) -> None:
        """Non-production environments may use localhost OIDC for local testing."""
        settings = _settings(
            env="staging",
            oidc_jwks_uri="http://localhost:8080/realms/ajenda/protocol/openid-connect/certs",
            oidc_issuer="http://localhost:8080/realms/ajenda",
        )
        settings.validate_runtime_contract()  # Must not raise

    def test_development_with_local_queue_is_allowed(self) -> None:
        settings = _settings(env="development", queue_adapter="local", queue_url=None)
        settings.validate_runtime_contract()  # Must not raise


# ---------------------------------------------------------------------------
# Queue adapter guards (existing — regression coverage)
# ---------------------------------------------------------------------------


class TestQueueAdapterGuards:
    def test_redis_adapter_without_url_raises(self) -> None:
        settings = _settings(queue_adapter="redis", queue_url=None)
        with pytest.raises(ValueError, match="AJENDA_QUEUE_URL is required"):
            settings.validate_runtime_contract()

    def test_redis_adapter_with_empty_url_raises(self) -> None:
        settings = _settings(queue_adapter="redis", queue_url="   ")
        with pytest.raises(ValueError, match="AJENDA_QUEUE_URL is required"):
            settings.validate_runtime_contract()

    def test_local_adapter_in_production_raises(self) -> None:
        settings = _settings(queue_adapter="local", queue_url=None)
        with pytest.raises(ValueError, match="AJENDA_QUEUE_ADAPTER=local is forbidden in production"):
            settings.validate_runtime_contract()


# ---------------------------------------------------------------------------
# OIDC localhost guards (new)
# ---------------------------------------------------------------------------


class TestOidcLocalhostGuards:
    def test_localhost_jwks_uri_in_production_raises(self) -> None:
        settings = _settings(oidc_jwks_uri="http://localhost:8080/realms/ajenda/protocol/openid-connect/certs")
        with pytest.raises(ValueError, match="AJENDA_OIDC_JWKS_URI must not point to localhost"):
            settings.validate_runtime_contract()

    def test_127_0_0_1_jwks_uri_in_production_raises(self) -> None:
        settings = _settings(oidc_jwks_uri="http://127.0.0.1:8080/realms/ajenda/protocol/openid-connect/certs")
        with pytest.raises(ValueError, match="AJENDA_OIDC_JWKS_URI must not point to localhost"):
            settings.validate_runtime_contract()

    def test_localhost_issuer_in_production_raises(self) -> None:
        settings = _settings(oidc_issuer="http://localhost:8080/realms/ajenda")
        with pytest.raises(ValueError, match="AJENDA_OIDC_ISSUER must not point to localhost"):
            settings.validate_runtime_contract()

    def test_127_0_0_1_issuer_in_production_raises(self) -> None:
        settings = _settings(oidc_issuer="http://127.0.0.1:8080/realms/ajenda")
        with pytest.raises(ValueError, match="AJENDA_OIDC_ISSUER must not point to localhost"):
            settings.validate_runtime_contract()

    def test_real_idp_jwks_uri_passes(self) -> None:
        settings = _settings(oidc_jwks_uri="https://auth.example.com/realms/ajenda/protocol/openid-connect/certs")
        settings.validate_runtime_contract()  # Must not raise

    def test_real_idp_issuer_passes(self) -> None:
        settings = _settings(oidc_issuer="https://auth.example.com/realms/ajenda")
        settings.validate_runtime_contract()  # Must not raise

    def test_error_message_includes_current_value(self) -> None:
        """The error message must include the misconfigured value for easy debugging."""
        bad_uri = "http://localhost:9999/realms/test/protocol/openid-connect/certs"
        settings = _settings(oidc_jwks_uri=bad_uri)
        with pytest.raises(ValueError) as exc_info:
            settings.validate_runtime_contract()
        assert bad_uri in str(exc_info.value)

    def test_error_message_includes_guidance(self) -> None:
        """The error message must tell the operator what to do."""
        settings = _settings(oidc_jwks_uri="http://localhost:8080/certs")
        with pytest.raises(ValueError) as exc_info:
            settings.validate_runtime_contract()
        # Must mention what to set it to
        assert "identity provider" in str(exc_info.value).lower() or "idp" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Rate limit sanity guards (new)
# ---------------------------------------------------------------------------


class TestRateLimitSanityGuards:
    def test_zero_rate_limit_requests_raises(self) -> None:
        settings = _settings(rate_limit_requests=0)
        with pytest.raises(ValueError, match="AJENDA_RATE_LIMIT_REQUESTS must be a positive integer"):
            settings.validate_runtime_contract()

    def test_negative_rate_limit_requests_raises(self) -> None:
        settings = _settings(rate_limit_requests=-10)
        with pytest.raises(ValueError, match="AJENDA_RATE_LIMIT_REQUESTS must be a positive integer"):
            settings.validate_runtime_contract()

    def test_zero_window_seconds_raises(self) -> None:
        settings = _settings(rate_limit_window_seconds=0)
        with pytest.raises(ValueError, match="AJENDA_RATE_LIMIT_WINDOW_SECONDS must be a positive integer"):
            settings.validate_runtime_contract()

    def test_negative_window_seconds_raises(self) -> None:
        settings = _settings(rate_limit_window_seconds=-60)
        with pytest.raises(ValueError, match="AJENDA_RATE_LIMIT_WINDOW_SECONDS must be a positive integer"):
            settings.validate_runtime_contract()

    def test_valid_rate_limit_config_passes(self) -> None:
        settings = _settings(rate_limit_requests=200, rate_limit_window_seconds=30)
        settings.validate_runtime_contract()  # Must not raise

    def test_rate_limit_guards_apply_in_all_environments(self) -> None:
        """Rate limit sanity is environment-agnostic — invalid values must always raise."""
        for env in ("development", "test", "staging", "production"):
            # Use redis adapter with a URL so the queue guard does not fire first.
            settings = _settings(
                env=env, queue_adapter="redis", queue_url="redis://redis:6379/0", rate_limit_requests=0
            )
            with pytest.raises(ValueError, match="AJENDA_RATE_LIMIT_REQUESTS"):
                settings.validate_runtime_contract()


class TestAuthzPolicyAsCodeGuards:
    def test_shadow_opa_requires_url(self) -> None:
        settings = _settings(authz_policy_mode="shadow_opa", authz_opa_url=None)
        with pytest.raises(ValueError, match="AJENDA_AUTHZ_OPA_URL is required"):
            settings.validate_runtime_contract()

    def test_enforce_opa_requires_url(self) -> None:
        settings = _settings(authz_policy_mode="enforce_opa", authz_opa_url="")
        with pytest.raises(ValueError, match="AJENDA_AUTHZ_OPA_URL is required"):
            settings.validate_runtime_contract()

    def test_rbac_mode_does_not_require_opa_url(self) -> None:
        settings = _settings(authz_policy_mode="rbac", authz_opa_url=None)
        settings.validate_runtime_contract()

    def test_non_positive_opa_timeout_raises(self) -> None:
        settings = _settings(
            authz_policy_mode="shadow_opa", authz_opa_url="http://opa:8181", authz_opa_timeout_seconds=0
        )
        with pytest.raises(ValueError, match="AJENDA_AUTHZ_OPA_TIMEOUT_SECONDS"):
            settings.validate_runtime_contract()
