"""Drift guards for single-host production hostname alignment."""

from __future__ import annotations

from pathlib import Path

INGRESS = Path("deploy/k8s/ingress.yaml")
CONFIGMAP = Path("deploy/k8s/configmap.yaml")
ENV_EXAMPLE = Path("deploy/compose/.env.prod.example")

CANONICAL_HOST = "ajenda.example.com"
CANONICAL_ORIGIN = f"https://{CANONICAL_HOST}"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_k8s_ingress_and_configmap_share_single_host_contract() -> None:
    ingress = _read(INGRESS)
    configmap = _read(CONFIGMAP)
    assert f"host: {CANONICAL_HOST}" in ingress
    assert f"{CANONICAL_ORIGIN}/verify-email" in configmap
    assert f"{CANONICAL_ORIGIN}" in configmap
    assert "app.your-domain.example.com" not in configmap


def test_compose_prod_example_matches_k8s_public_hostname_contract() -> None:
    env_example = _read(ENV_EXAMPLE)
    assert f"AJENDA_SIGNUP_VERIFY_URL_BASE={CANONICAL_ORIGIN}/verify-email" in env_example
    assert f"AJENDA_CORS_ALLOWED_ORIGINS={CANONICAL_ORIGIN}" in env_example
    assert "/v1/billing/webhook/stripe" in env_example
