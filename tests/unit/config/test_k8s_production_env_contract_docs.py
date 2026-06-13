"""Drift guards for Kubernetes production environment manifests.

These tests keep Kubernetes config/secret examples aligned with the same
production runtime contract guarded for Compose. They validate required key
presence and deployment wiring, not live Kubernetes behavior.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
K8S_CONFIGMAP = REPO_ROOT / "deploy" / "k8s" / "configmap.yaml"
K8S_SECRET_EXAMPLE = REPO_ROOT / "deploy" / "k8s" / "secret.example.yaml"
K8S_API_DEPLOYMENT = REPO_ROOT / "deploy" / "k8s" / "api-deployment.yaml"
K8S_WORKER_DEPLOYMENT = REPO_ROOT / "deploy" / "k8s" / "worker-deployment.yaml"

REQUIRED_K8S_CONFIG_KEYS = frozenset(
    {
        "AJENDA_ENV",
        "AJENDA_QUEUE_ADAPTER",
        "AJENDA_QUEUE_URL",
        "AJENDA_WORKER_TENANT_ID",
        "AJENDA_OIDC_ISSUER",
        "AJENDA_OIDC_JWKS_URI",
        "AJENDA_OIDC_AUDIENCE",
        "AJENDA_AUTHZ_POLICY_MODE",
        "AJENDA_AUTHZ_OPA_TIMEOUT_SECONDS",
        "AJENDA_BUDGET_POLICY_ENABLED",
        "AJENDA_BUDGET_POLICY_OBSERVE_ONLY",
        "AJENDA_BUDGET_POLICY_ENFORCE",
        "AJENDA_RATE_LIMIT_REQUESTS",
        "AJENDA_RATE_LIMIT_WINDOW_SECONDS",
    }
)

REQUIRED_K8S_SECRET_KEYS = frozenset(
    {
        "POSTGRES_PASSWORD",
        "AJENDA_DATABASE_URL",
        "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY",
        "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY",
    }
)

OPTIONAL_K8S_SECRET_KEYS = frozenset(
    {
        "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY_PREV",
        "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY_PREV",
    }
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _yaml_mapping_keys_under_section(text: str, section: str) -> set[str]:
    section_match = re.search(rf"^{re.escape(section)}:\n(?P<body>(?:^  [A-Z0-9_]+:.*\n?)+)", text, flags=re.MULTILINE)
    if section_match is None:
        return set()
    return set(re.findall(r"^  ([A-Z][A-Z0-9_]*):", section_match.group("body"), flags=re.MULTILINE))


def test_k8s_configmap_contains_required_production_config_keys() -> None:
    config_keys = _yaml_mapping_keys_under_section(_read(K8S_CONFIGMAP), "data")

    missing = REQUIRED_K8S_CONFIG_KEYS - config_keys

    assert not missing, f"Missing required production config keys from {K8S_CONFIGMAP}: {sorted(missing)}"


def test_k8s_secret_example_contains_required_secret_keys() -> None:
    secret_keys = _yaml_mapping_keys_under_section(_read(K8S_SECRET_EXAMPLE), "stringData")

    missing = REQUIRED_K8S_SECRET_KEYS - secret_keys

    assert not missing, f"Missing required production secret keys from {K8S_SECRET_EXAMPLE}: {sorted(missing)}"


def test_k8s_secret_example_keeps_optional_rotation_key_documented() -> None:
    secret_keys = _yaml_mapping_keys_under_section(_read(K8S_SECRET_EXAMPLE), "stringData")

    missing = OPTIONAL_K8S_SECRET_KEYS - secret_keys

    assert not missing, f"Missing optional production secret keys from {K8S_SECRET_EXAMPLE}: {sorted(missing)}"


def test_k8s_configmap_uses_production_runtime_mode_and_redis_queue() -> None:
    configmap = _read(K8S_CONFIGMAP)

    assert 'AJENDA_ENV: "production"' in configmap
    assert 'AJENDA_QUEUE_ADAPTER: "redis"' in configmap
    assert 'AJENDA_QUEUE_ADAPTER: "local"' not in configmap


def test_api_deployment_imports_configmap_and_secret() -> None:
    deployment = _read(K8S_API_DEPLOYMENT)

    assert "configMapRef:" in deployment
    assert "name: ajenda-config" in deployment
    assert "secretRef:" in deployment
    assert "name: ajenda-secrets" in deployment


def test_worker_deployment_imports_configmap_and_secret() -> None:
    deployment = _read(K8S_WORKER_DEPLOYMENT)

    assert "configMapRef:" in deployment
    assert "name: ajenda-config" in deployment
    assert "secretRef:" in deployment
    assert "name: ajenda-secrets" in deployment


def test_worker_deployment_preserves_pod_name_worker_identity_source() -> None:
    deployment = _read(K8S_WORKER_DEPLOYMENT)

    assert "name: POD_NAME" in deployment
    assert "fieldPath: metadata.name" in deployment
