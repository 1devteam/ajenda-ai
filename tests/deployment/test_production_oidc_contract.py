from __future__ import annotations

from pathlib import Path


def test_compose_production_env_documents_full_oidc_contract() -> None:
    content = Path("deploy/compose/.env.prod.example").read_text(encoding="utf-8")

    assert "AJENDA_OIDC_ISSUER=" in content
    assert "AJENDA_OIDC_JWKS_URI=" in content
    assert "AJENDA_OIDC_AUDIENCE=" in content
    assert "localhost" not in _active_env_value(content, "AJENDA_OIDC_ISSUER")
    assert "localhost" not in _active_env_value(content, "AJENDA_OIDC_JWKS_URI")


def test_k8s_configmap_documents_full_oidc_contract() -> None:
    content = Path("deploy/k8s/configmap.yaml").read_text(encoding="utf-8")

    assert "AJENDA_OIDC_ISSUER" in content
    assert "AJENDA_OIDC_JWKS_URI" in content
    assert "AJENDA_OIDC_AUDIENCE" in content


def test_production_worker_tenant_is_explicitly_documented() -> None:
    compose_env = Path("deploy/compose/.env.prod.example").read_text(encoding="utf-8")
    k8s_config = Path("deploy/k8s/configmap.yaml").read_text(encoding="utf-8")

    assert "AJENDA_WORKER_TENANT_ID=" in compose_env
    assert "AJENDA_WORKER_TENANT_ID" in k8s_config
    assert "AJENDA_WORKER_TENANT_ID=default" not in compose_env


def _active_env_value(content: str, key: str) -> str:
    prefix = f"{key}="
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.removeprefix(prefix)
    raise AssertionError(f"{key} not found")
