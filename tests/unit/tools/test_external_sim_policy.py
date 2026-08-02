from __future__ import annotations

import pytest

from backend.services.tools.external_sim_policy import require_external_secret


def test_external_simulation_fails_closed_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AJENDA_ALLOW_SIMULATED_EXTERNAL", raising=False)

    with pytest.raises(ValueError, match="requires a runtime credential"):
        require_external_secret(secret=None, action="provider.external_read")


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
def test_external_simulation_requires_explicit_non_production_opt_in(
    monkeypatch, value: str
) -> None:
    monkeypatch.setenv("AJENDA_ENV", "development")
    monkeypatch.setenv("AJENDA_ALLOW_SIMULATED_EXTERNAL", value)

    require_external_secret(secret=None, action="provider.external_read")


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
def test_external_simulation_is_rejected_in_production(monkeypatch, value: str) -> None:
    monkeypatch.setenv("AJENDA_ENV", "production")
    monkeypatch.setenv("AJENDA_ALLOW_SIMULATED_EXTERNAL", value)

    with pytest.raises(ValueError, match="requires a runtime credential"):
        require_external_secret(secret=None, action="provider.external_read")


def test_real_secret_never_requires_simulation_flag(monkeypatch) -> None:
    monkeypatch.delenv("AJENDA_ALLOW_SIMULATED_EXTERNAL", raising=False)

    require_external_secret(secret="runtime-secret", action="provider.external_read")
