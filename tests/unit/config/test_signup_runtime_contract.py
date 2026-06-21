"""Unit tests for signup-related runtime contract validation."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from backend.app.config import Settings

_VALID_WEBHOOK_KEY = Fernet.generate_key().decode()
_VALID_RUNTIME_KEY = Fernet.generate_key().decode()


def _settings(**overrides) -> Settings:
    defaults = {
        "env": "production",
        "queue_adapter": "redis",
        "queue_url": "redis://redis:6379/0",
        "worker_tenant_id": "00000000-0000-0000-0000-000000000001",
        "oidc_jwks_uri": "https://idp.example.com/realms/ajenda/protocol/openid-connect/certs",
        "oidc_issuer": "https://idp.example.com/realms/ajenda",
        "webhook_secret_encryption_key": _VALID_WEBHOOK_KEY,
        "runtime_secret_encryption_key": _VALID_RUNTIME_KEY,
        "STRIPE_SECRET_KEY": "sk_test_placeholder",
        "STRIPE_WEBHOOK_SECRET": "whsec_placeholder",
        "email_provider": "resend",
        "resend_api_key": "re_test_key",
        "email_from": "Ajenda AI <onboarding@ajenda.ai>",
        "signup_verify_url_base": "https://app.ajenda.ai/verify-email",
    }
    defaults.update(overrides)
    return Settings.model_construct(**defaults)


def test_production_rejects_logging_email_provider() -> None:
    settings = _settings(email_provider="logging")
    with pytest.raises(ValueError, match="AJENDA_EMAIL_PROVIDER=logging is forbidden"):
        settings.validate_runtime_contract()


def test_production_requires_resend_configuration() -> None:
    settings = _settings(resend_api_key="")
    with pytest.raises(ValueError, match="AJENDA_RESEND_API_KEY is required"):
        settings.validate_runtime_contract()


def test_signup_idempotency_required_defaults_to_production() -> None:
    settings = Settings.model_construct(env="production")
    assert settings.signup_idempotency_required is True
    settings_dev = Settings.model_construct(env="development")
    assert settings_dev.signup_idempotency_required is False
