"""Source-backed runtime security observations, without enforcement authority.

Security findings require positive evidence of a broken tenant or lease boundary.
Absent historical records are not treated as demonstrated violations.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID


def inspect_runtime_security(
    *,
    tenant_id: str,
    mission_id: UUID,
    tasks: list[Any],
    leases: list[Any],
    evidence: list[Any],
    audits: list[Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    known_tasks = {str(task.id) for task in tasks if task.tenant_id == tenant_id and task.mission_id == mission_id}

    for task in tasks:
        if task.tenant_id != tenant_id or task.mission_id != mission_id:
            findings.append({
                "category": "security_tenant_boundary",
                "code": f"task:{task.id}:scope_mismatch",
                "severity": "error",
            })
    for lease in leases:
        if lease.tenant_id != tenant_id or str(lease.task_id) not in known_tasks:
            findings.append({
                "category": "security_lease_boundary",
                "code": f"lease:{lease.id}:tenant_or_task_mismatch",
                "severity": "error",
            })
    for record in evidence:
        if record.tenant_id != tenant_id or record.mission_id != mission_id:
            findings.append({
                "category": "security_evidence_boundary",
                "code": f"evidence:{record.id}:scope_mismatch",
                "severity": "error",
            })
        elif record.execution_task_id is not None and str(record.execution_task_id) not in known_tasks:
            findings.append({
                "category": "security_evidence_boundary",
                "code": f"evidence:{record.id}:unrecognized_task",
                "severity": "error",
            })
    for event in audits:
        if event.tenant_id != tenant_id or event.mission_id != mission_id:
            findings.append({
                "category": "security_audit_boundary",
                "code": f"audit:{event.id}:scope_mismatch",
                "severity": "error",
            })
    return findings
