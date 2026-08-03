"""Drift guards for production environment documentation.

These tests keep the production Compose environment template and operator
contract aligned with the production runtime settings contract. They do not
validate secret values; they prevent required configuration names from being
silently dropped from docs or templates.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PROD_ENV_TEMPLATE = REPO_ROOT / "deploy" / "compose" / ".env.prod.example"
PROD_ENV_CONTRACT = REPO_ROOT / "docs" / "deployment" / "production-env-contract.md"

REQUIRED_PRODUCTION_ENV_VARS = frozenset(
    {
        "POSTGRES_PASSWORD",
        "AJENDA_DATABASE_URL",
        "AJENDA_ENV",
        "AJENDA_QUEUE_ADAPTER",
        "AJENDA_QUEUE_URL",
        "AJENDA_WORKER_TENANT_MODE",
        "AJENDA_WORKER_TENANT_REFRESH_SECONDS",
        "AJENDA_WORKER_TENANT_ID",
        "AJENDA_OIDC_ISSUER",
        "AJENDA_OIDC_JWKS_URI",
        "AJENDA_OIDC_AUDIENCE",
        "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY",
        "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY",
        "AJENDA_AUTHZ_POLICY_MODE",
        "AJENDA_AUTHZ_OPA_TIMEOUT_SECONDS",
        "AJENDA_BUDGET_POLICY_ENABLED",
        "AJENDA_BUDGET_POLICY_OBSERVE_ONLY",
        "AJENDA_BUDGET_POLICY_ENFORCE",
        "AJENDA_MISSION_INTERPRETER_ENABLED",
        "AJENDA_MISSION_INTERPRETER_PRIVATE_HOST_ALLOWLIST",
        "AJENDA_MISSION_INTERPRETER_TIMEOUT_SECONDS",
        "AJENDA_MISSION_INTERPRETER_MAX_TOKENS",
    }
)

OPTIONAL_BUT_DOCUMENTED_PRODUCTION_ENV_VARS = frozenset(
    {
        "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY_PREV",
        "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY_PREV",
        "AJENDA_AUTHZ_OPA_URL",
        "AJENDA_MISSION_INTERPRETER_BASE_URL",
        "AJENDA_MISSION_INTERPRETER_MODEL",
        "AJENDA_MISSION_INTERPRETER_API_KEY",
    }
)

PRODUCTION_ENV_GUARDRAILS = (
    "local queue adapter",
    "Redis adapter without AJENDA_QUEUE_URL",
    "localhost OIDC issuer/JWKS",
    "missing or invalid webhook/runtime secret encryption key",
    "deterministic development/test webhook/runtime key",
    "default or blank worker tenant id",
    "invalid rate-limit settings",
    "OPA modes without OPA URL",
    "enabled mission interpreter with a blank endpoint or model",
    "invalid or credentialed mission interpreter endpoint",
    "mission interpreter endpoint host outside its explicit private allowlist",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _env_template_keys(template: str) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", template, flags=re.MULTILINE))


def test_production_env_template_documents_required_runtime_contract_keys() -> None:
    template_keys = _env_template_keys(_read(PROD_ENV_TEMPLATE))

    missing = REQUIRED_PRODUCTION_ENV_VARS - template_keys

    assert not missing, f"Missing required production env vars from {PROD_ENV_TEMPLATE}: {sorted(missing)}"


def test_production_env_contract_documents_required_runtime_contract_keys() -> None:
    contract = _read(PROD_ENV_CONTRACT)

    missing = {env_var for env_var in REQUIRED_PRODUCTION_ENV_VARS if env_var not in contract}

    assert not missing, f"Missing required production env vars from {PROD_ENV_CONTRACT}: {sorted(missing)}"


def test_optional_rotation_and_policy_env_vars_stay_documented() -> None:
    template = _read(PROD_ENV_TEMPLATE)
    contract = _read(PROD_ENV_CONTRACT)

    missing_from_template = {
        env_var for env_var in OPTIONAL_BUT_DOCUMENTED_PRODUCTION_ENV_VARS if env_var not in template
    }
    missing_from_contract = {
        env_var for env_var in OPTIONAL_BUT_DOCUMENTED_PRODUCTION_ENV_VARS if env_var not in contract
    }

    assert not missing_from_template, (
        f"Missing optional documented production env vars from {PROD_ENV_TEMPLATE}: {sorted(missing_from_template)}"
    )
    assert not missing_from_contract, (
        f"Missing optional documented production env vars from {PROD_ENV_CONTRACT}: {sorted(missing_from_contract)}"
    )


def test_production_env_template_does_not_ship_development_runtime_mode() -> None:
    template = _read(PROD_ENV_TEMPLATE)

    assert "AJENDA_ENV=production" in template
    assert "AJENDA_QUEUE_ADAPTER=redis" in template
    assert "AJENDA_QUEUE_ADAPTER=local" not in template


def test_production_env_contract_documents_startup_guardrails() -> None:
    contract = _read(PROD_ENV_CONTRACT)

    missing = {guardrail for guardrail in PRODUCTION_ENV_GUARDRAILS if guardrail not in contract}

    assert not missing, f"Missing production startup guardrails from {PROD_ENV_CONTRACT}: {sorted(missing)}"
