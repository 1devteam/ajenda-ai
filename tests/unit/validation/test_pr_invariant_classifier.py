from __future__ import annotations

from scripts.validation.pr_invariant_classifier import classify_risk_domains, evaluate_proof_rules


def _rule_ids(findings):  # type: ignore[no-untyped-def]
    return {finding.rule_id for finding in findings}


def test_new_oauth_connector_requires_full_authority_and_runtime_proof() -> None:
    changed = {
        "backend/api/routes/provider_credentials.py",
        "backend/services/credentials/google_docs_oauth_connect.py",
        "backend/services/credentials/google_docs_runtime_token.py",
        "backend/services/credentials/management_service.py",
        "tests/unit/credentials/test_google_docs_oauth_connect.py",
    }
    findings = evaluate_proof_rules(
        changed_files=changed,
        added_files={
            "backend/services/credentials/google_docs_oauth_connect.py",
            "backend/services/credentials/google_docs_runtime_token.py",
        },
    )

    ids = _rule_ids(findings)
    assert "new-oauth-authority-ledger" in ids
    assert "new-oauth-route-proof" in ids
    assert "new-oauth-runtime-resolution" in ids
    assert "new-oauth-integration-proof" in ids


def test_new_oauth_connector_passes_deterministic_requirements_when_proofs_change() -> None:
    changed = {
        "backend/api/routes/provider_credentials.py",
        "backend/services/credentials/google_docs_oauth_connect.py",
        "backend/services/credentials/google_docs_runtime_token.py",
        "backend/services/credentials/sqlalchemy_repository.py",
        "docs/contracts/authority-ledger.v1.yaml",
        "tests/contract/api/test_provider_credentials_routes.py",
        "tests/integration/credentials/test_google_docs_runtime_real.py",
    }
    findings = evaluate_proof_rules(
        changed_files=changed,
        added_files={
            "backend/services/credentials/google_docs_oauth_connect.py",
            "backend/services/credentials/google_docs_runtime_token.py",
        },
    )

    assert not [finding for finding in findings if finding.severity == "fail"]


def test_new_action_module_requires_registry_and_tool_tests() -> None:
    findings = evaluate_proof_rules(
        changed_files={"backend/services/tools/example_actions.py"},
        added_files={"backend/services/tools/example_actions.py"},
    )

    ids = _rule_ids(findings)
    assert "new-action-registration" in ids
    assert "new-action-proof" in ids


def test_migration_requires_migration_contract_test() -> None:
    findings = evaluate_proof_rules(
        changed_files={"alembic/versions/0041_example.py", "backend/domain/example.py"},
        added_files={"alembic/versions/0041_example.py"},
    )

    assert "migration-contract-proof" in _rule_ids(findings)


def test_risk_classifier_maps_multi_layer_change() -> None:
    profiles = classify_risk_domains(
        {
            "backend/api/routes/provider_credentials.py",
            "backend/app/config.py",
            "frontend/src/api/client.ts",
            "alembic/versions/0041_example.py",
        }
    )

    ids = {profile.id for profile in profiles}
    assert "tenant-isolation" in ids
    assert "credential-boundary" in ids
    assert "configuration" in ids
    assert "frontend-contract" in ids
    assert "persistence" in ids


def test_core_runtime_change_without_targeted_runtime_test_is_review_not_failure() -> None:
    findings = evaluate_proof_rules(
        changed_files={"backend/services/execution_coordinator.py"},
        added_files=set(),
    )

    runtime_findings = [finding for finding in findings if finding.rule_id == "runtime-spine-proof"]
    assert len(runtime_findings) == 1
    assert runtime_findings[0].severity == "review"
