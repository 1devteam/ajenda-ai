from __future__ import annotations

import pytest

from backend.app.config import Settings
from backend.services.credentials.platform_master import (
    PlatformMasterNotConfiguredError,
    platform_master_ready_for,
    resolve_platform_master_secret,
)


def _settings(**overrides: object) -> Settings:
    return Settings.model_construct(env="test", **overrides)


def test_resolve_hubspot_platform_master_secret() -> None:
    settings = _settings(
        hubspot_platform_master_key_enabled=True,
        hubspot_platform_master_key="hubspot-test-key",
    )
    secret = resolve_platform_master_secret(provider="external_crm", integration="hubspot", settings=settings)
    assert secret == "hubspot-test-key"


def test_resolve_email_platform_master_secret() -> None:
    smtp_secret = (
        '{"host":"smtp.example.com","port":587,"user":"send@ajenda.ai","password":"secret","from":"send@ajenda.ai"}'
    )
    settings = _settings(
        email_platform_master_key_enabled=True,
        email_platform_smtp_secret=smtp_secret,
    )
    secret = resolve_platform_master_secret(provider="external_email", integration="smtp", settings=settings)
    assert secret == smtp_secret


def test_platform_master_not_configured_for_unknown_provider() -> None:
    with pytest.raises(PlatformMasterNotConfiguredError):
        resolve_platform_master_secret(provider="external_read_provider", integration="generic", settings=_settings())


def test_platform_master_ready_for_email() -> None:
    smtp_secret = '{"host":"smtp.example.com","user":"send@ajenda.ai","password":"secret"}'
    settings = _settings(
        email_platform_master_key_enabled=True,
        email_platform_smtp_secret=smtp_secret,
    )
    assert platform_master_ready_for(provider="external_email", integration="smtp", settings=settings) is True
    assert platform_master_ready_for(provider="external_email", integration="gmail", settings=settings) is False
