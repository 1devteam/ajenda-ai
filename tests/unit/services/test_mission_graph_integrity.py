from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector
from backend.services.mission_graph_integrity import evaluate_admission_integrity


def _graph(reference: dict[str, object] | None = None) -> dict[str, object]:
    contract: dict[str, object] = {"tool_invocation": {"action": "web.research", "input": {}}}
    if reference:
        contract["credential_reference"] = reference
    return {
        "nodes": [
            {
                "key": "research",
                "metadata": {"job_key": "research.discover_prospects"},
                "input_contract": contract,
                "output_contract": {"artifact": "research_report"},
            }
        ]
    }


def test_admission_preflight_decrypts_tenant_credential_without_exposing_secret() -> None:
    protector = RuntimeCredentialSecretProtector(
        encryption_key=RuntimeCredentialSecretProtector.generate_key().encode()
    )
    session = MagicMock()
    session.scalars.return_value.first.return_value = SimpleNamespace(
        provider="external_read_provider",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        deleted=False,
        secret_ciphertext=protector.encrypt_secret("secret-value"),
    )
    reference = {
        "credential_id": "cred-1",
        "provider": "external_read_provider",
        "credential_type": "api_key",
    }

    report = evaluate_admission_integrity(
        session=session,
        tenant_id="tenant-1",
        instruction="Research competitors and produce a report.",
        task_graph=_graph(reference),
        secret_protector=protector,
    )

    assert report["status"] == "clear"
    assert "secret-value" not in str(report)
    session.commit.assert_not_called()
    session.flush.assert_not_called()


def test_admission_preflight_blocks_wrong_runtime_key() -> None:
    stored = RuntimeCredentialSecretProtector(encryption_key=RuntimeCredentialSecretProtector.generate_key().encode())
    active = RuntimeCredentialSecretProtector(encryption_key=RuntimeCredentialSecretProtector.generate_key().encode())
    session = MagicMock()
    session.scalars.return_value.first.return_value = SimpleNamespace(
        provider="external_read_provider",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        deleted=False,
        secret_ciphertext=stored.encrypt_secret("secret-value"),
    )

    report = evaluate_admission_integrity(
        session=session,
        tenant_id="tenant-1",
        instruction="Read Google Contacts.",
        task_graph=_graph(
            {"credential_id": "cred-1", "provider": "external_read_provider", "credential_type": "api_key"}
        ),
        secret_protector=active,
    )

    assert report["status"] == "blocked"
    assert [item["code"] for item in report["findings"]] == ["mission_credential.not_decryptable"]


def test_compare_qualification_facts_does_not_require_report_artifact() -> None:
    session = MagicMock()
    report = evaluate_admission_integrity(
        session=session,
        tenant_id="tenant-1",
        instruction="Compare qualification evidence and rank the strongest CRM records.",
        task_graph={
            "nodes": [
                {
                    "key": "qualify",
                    "metadata": {"job_key": "sales.qualify_prospects"},
                    "output_contract": {"artifact": "qualified_prospects"},
                }
            ]
        },
    )
    assert report["status"] == "clear"
    assert not any(item["code"] == "mission_deliverable.report_not_materialized" for item in report["findings"])
