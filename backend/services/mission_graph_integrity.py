"""Fail-closed GRAFT checks for mission runtime admission."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from backend.repositories.provider_runtime_credential_repository import ProviderRuntimeCredentialRepository
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector

# ``compare`` is an ordinary qualification operation and does not by itself
# request a report artifact. Require an explicit report/comparison deliverable
# so runtime admission does not reject CRM ranking missions that compare facts.
REPORT_RE = re.compile(
    r"\b(?:comparison\s+table|comparison\s+report|research\s+report|report\b|highlight\b|evidence\s+gap)", re.I
)
# These artifacts are whole-document/report-like outputs.  Keep this list
# aligned with job_catalog producers so admission does not mistake a typed
# analysis artifact for an unmaterialized generic report.
REPORT_ARTIFACTS = frozenset(
    {
        "comparison_report",
        "mission_report",
        "research_report",
        "business_review_report",
        "goal_progress_evaluation",
    }
)
CONTACTS_RE = re.compile(
    r"\bgoogle\s+contacts?\b|\b(?:check|read|list|show|fetch|get)\s+(?:my\s+|the\s+)?contacts?\b", re.I
)


def evaluate_admission_integrity(
    *,
    session: Session,
    tenant_id: str,
    instruction: str,
    task_graph: dict[str, Any],
    secret_protector: RuntimeCredentialSecretProtector | None = None,
) -> dict[str, Any]:
    """Inspect graph semantics and credential decryptability without mutation."""

    nodes = [node for node in task_graph.get("nodes", []) if isinstance(node, dict)]
    findings: list[dict[str, Any]] = []
    if any(line.lstrip().startswith(">") for line in instruction.splitlines()):
        findings.append(_finding("mission_input.markdown_quote_leaked", "Markdown quote prefixes reached admission."))

    contact_nodes = [
        str(node.get("key") or node.get("node_key") or "")
        for node in nodes
        if str((node.get("metadata") or {}).get("job_key") or "") == "ops.google_contacts_read"
    ]
    if contact_nodes and CONTACTS_RE.search(instruction) is None:
        findings.append(
            _finding("mission_selection.unsupported_google_contacts", "Google Contacts lacks an explicit request.")
        )

    artifacts = {str((node.get("output_contract") or {}).get("artifact") or "") for node in nodes}
    if REPORT_RE.search(instruction) and not artifacts.intersection(REPORT_ARTIFACTS):
        findings.append(
            _finding("mission_deliverable.report_not_materialized", "Requested report has no producing node.")
        )

    repo = ProviderRuntimeCredentialRepository(session)
    protector = secret_protector or RuntimeCredentialSecretProtector()
    for node in nodes:
        raw_contract = node.get("input_contract")
        contract: dict[str, Any] = raw_contract if isinstance(raw_contract, dict) else {}
        reference = contract.get("credential_reference")
        if not isinstance(reference, dict):
            continue
        credential_id = str(reference.get("credential_id") or "")
        record = repo.get_for_tenant(tenant_id=tenant_id, credential_id=credential_id)
        node_key = str(node.get("key") or node.get("node_key") or "")
        if record is None:
            findings.append(
                _finding("mission_credential.not_visible", "Credential is not visible for tenant.", node_key=node_key)
            )
            continue
        if not record.enabled or record.revoked or record.deleted:
            findings.append(
                _finding("mission_credential.ineligible", "Credential is not runtime eligible.", node_key=node_key)
            )
            continue
        if record.provider != reference.get("provider") or record.credential_type != reference.get("credential_type"):
            findings.append(
                _finding(
                    "mission_credential.reference_mismatch",
                    "Credential metadata does not match reference.",
                    node_key=node_key,
                )
            )
            continue
        try:
            protector.decrypt_secret(record.secret_ciphertext)
        except (TypeError, ValueError):
            findings.append(
                _finding(
                    "mission_credential.not_decryptable",
                    "Credential cannot be decrypted by the active runtime key.",
                    node_key=node_key,
                )
            )

    payload = {"tenant_id": tenant_id, "instruction": instruction, "task_graph": task_graph}
    return {
        "schema_version": "1.0",
        "status": "blocked" if findings else "clear",
        "findings": findings,
        "context_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest(),
        "policy": {"enforcement": "runtime_admission", "mutates_runtime": False},
    }


def _finding(code: str, message: str, *, node_key: str | None = None) -> dict[str, Any]:
    finding: dict[str, Any] = {"code": code, "severity": "blocking", "message": message}
    if node_key:
        finding["node_key"] = node_key
    return finding
