#!/usr/bin/env python3
"""CI-safe M11 capstone slice: seed charter → draft → approve → CRM log.

Runs inside the API container against AJENDA_PROOF_WORKER_TENANT_ID (no HTTP/API key).
Does not send email unless AJENDA_BRAIN_CAPSTONE_SEND=1 and platform SMTP is configured.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.services.brain_capability_check import build_brain_capability_report
from backend.services.document_artifacts import update_review_status
from backend.services.operating_charter import dogfood_operating_charter
from backend.workers.handlers.tool_invoke import tool_invoke_handler


def _seed_profile(*, session, tenant_id: str) -> None:
    repo = BusinessProfileRepository(session)
    profile = repo.get_or_create_active_profile(tenant_id=tenant_id)
    now = datetime.now(UTC)
    facts = {
        "business_name": {"value": "Ajenda AI"},
        "products_services": {
            "value": "Governed mission runtime\nHybrid retrieval\nClerical worker automation",
        },
        "operator_notes": {
            "value": "Prepare drafts freely. External send requires review queue approval.",
        },
    }
    for category, approved_fact in facts.items():
        repo.upsert_approved_fact(
            profile=profile,
            category=category,
            approved_fact=approved_fact,
            actor_id="brain-capstone-runtime-proof",
            updated_at=now,
            provenance_metadata={"source": "brain-capstone-runtime-proof"},
        )
    charter = dogfood_operating_charter()
    repo.upsert_approved_fact(
        profile=profile,
        category="operating_charter",
        approved_fact={"value": charter.to_fact_payload()},
        actor_id="brain-capstone-runtime-proof",
        updated_at=now,
        provenance_metadata={"source": "brain-capstone-runtime-proof"},
    )
    session.commit()


def _run_tool_invoke(
    *,
    session_factory,
    tenant_id: str,
    action: str,
    side_effect_class: str,
    input_payload: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    session = session_factory()
    try:
        suffix = uuid.uuid4().hex[:10]
        adapter_class = {
            "none": "none",
            "internal_write": "non_idempotent_write",
            "external_write": "external_write",
            "external_send": "external_send",
        }.get(side_effect_class, "none")
        capability = Capability(
            tenant_id=tenant_id,
            name=f"capstone-{action}-{suffix}",
            version="1.0.0",
            description=f"Capstone proof: {action}",
            supported_task_types=["tool.invoke", action],
            input_schema_hints={},
            output_schema_hints={},
            required_permissions=[],
            required_tools=[action],
            risk_level="medium",
            approval_requirements={"required": False, "generated_by": "brain-capstone-runtime-proof"},
            evidence_expectations=[f"{action} evidence"],
            execution_constraints={},
            enabled=True,
            schema_version=1,
        )
        session.add(capability)
        session.flush()
        adapter = CapabilityAdapter(
            tenant_id=tenant_id,
            name=f"capstone-{action}-adapter-{suffix}",
            version="1.0.0",
            capability_id=capability.id,
            capability_name=capability.name,
            capability_version=capability.version,
            supported_task_types=["tool.invoke", action],
            input_contract={},
            output_contract={},
            required_permissions=[],
            required_tools=[action],
            execution_mode="queued",
            risk_level="medium",
            approval_requirements={"required": False, "generated_by": "brain-capstone-runtime-proof"},
            evidence_expectations=[f"{action} evidence"],
            timeout_retry_hints={},
            idempotency_expectations={},
            side_effect_classification=adapter_class,
            enabled=True,
            schema_version=1,
        )
        session.add(adapter)
        session.flush()

        mission = Mission(tenant_id=tenant_id, objective=label, status="running")
        session.add(mission)
        session.flush()
        metadata: dict[str, Any] = {
            "task_type": "tool.invoke",
            "launched_by": "brain-capstone-runtime-proof",
            "tool_invocation": {"schema_version": 1, "action": action, "input": input_payload},
            "capability_reference": {"capability_id": str(capability.id)},
            "adapter_reference": {"adapter_id": str(adapter.id)},
        }
        if side_effect_class != "none":
            metadata["execution_constraints"] = {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": [action],
                    "reason": "brain-capstone-runtime-proof",
                    "approved_by": "live-runtime-proof",
                }
            }
        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title=label,
            description="brain-capstone-runtime-proof",
            status=ExecutionTaskState.RUNNING.value,
            metadata_json=metadata,
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        session.add(task)
        session.flush()
        task_id = task.id
        session.commit()
    finally:
        session.close()

    session = session_factory()
    try:
        current = session.get(ExecutionTask, task_id)
        ctx = {
            "worker_id": "brain-capstone-runtime-proof",
            "tenant_id": tenant_id,
            "lease_id": str(uuid.uuid4()),
            "session_factory": session_factory,
        }
        result = tool_invoke_handler(current, ctx)
        current.status = ExecutionTaskState.COMPLETED.value
        session.commit()
        return {"ok": True, "summary": result.get("summary"), "output": result.get("output")}
    except Exception as exc:
        session.rollback()
        return {"ok": False, "error": str(exc)}
    finally:
        session.close()


def main() -> int:
    tenant_id = os.environ.get("AJENDA_PROOF_WORKER_TENANT_ID", "").strip()
    if not tenant_id:
        print("ERROR: AJENDA_PROOF_WORKER_TENANT_ID is required", file=sys.stderr)
        return 2

    settings = get_settings()
    runtime = DatabaseRuntime(settings)
    steps: list[dict[str, str]] = []
    artifact_id: str | None = None

    try:
        session = runtime.session_factory()
        try:
            _seed_profile(session=session, tenant_id=tenant_id)
        finally:
            session.close()

        draft = _run_tool_invoke(
            session_factory=runtime.session_factory,
            tenant_id=tenant_id,
            action="gtm.email_draft",
            side_effect_class="none",
            input_payload={
                "recipient": "ops@northwind-logistics.example",
                "topic": "Ajenda clerical worker pilot",
                "tone": "professional",
                "context": {"capstone_proof": True},
            },
            label="Capstone draft",
        )
        if not draft.get("ok"):
            print(json.dumps({"ok": False, "step": "draft", "error": draft.get("error")}))
            return 1
        artifact_id = (draft.get("output") or {}).get("artifact_id")
        mode = (draft.get("output") or {}).get("generation_mode", "template")
        if not artifact_id:
            print(json.dumps({"ok": False, "step": "draft", "error": "missing artifact_id"}))
            return 1
        steps.append({"step": "draft", "status": "PASS", "note": f"artifact={artifact_id}, mode={mode}"})

        session = runtime.session_factory()
        try:
            update_review_status(
                session,
                tenant_id=tenant_id,
                artifact_id=artifact_id,
                review_status="approved",
                actor="live-runtime-proof",
                note="capstone runtime proof",
            )
            session.commit()
        finally:
            session.close()
        steps.append({"step": "approve", "status": "PASS", "note": "approved"})

        if os.environ.get("AJENDA_BRAIN_CAPSTONE_SEND") == "1":
            send = _run_tool_invoke(
                session_factory=runtime.session_factory,
                tenant_id=tenant_id,
                action="gtm.email_send",
                side_effect_class="external_send",
                input_payload={"to": "ops@northwind-logistics.example", "artifact_id": artifact_id},
                label="Capstone send",
            )
            send_status = "PASS" if send.get("ok") else "FAIL"
            steps.append({"step": "send", "status": send_status, "note": str(send.get("summary") or send.get("error"))})
            if not send.get("ok"):
                print(json.dumps({"ok": False, "steps": steps}))
                return 1
        else:
            steps.append({"step": "send", "status": "SKIP", "note": "AJENDA_BRAIN_CAPSTONE_SEND not set"})

        crm = _run_tool_invoke(
            session_factory=runtime.session_factory,
            tenant_id=tenant_id,
            action="gtm.crm_upsert",
            side_effect_class="internal_write",
            input_payload={
                "record_type": "contact",
                "data": {
                    "email": "jordan.lee@northwind-logistics.example",
                    "firstname": "Jordan",
                    "lastname": "Lee",
                    "company": "Northwind Logistics",
                    "notes": f"Capstone proof artifact={artifact_id}",
                },
            },
            label="Capstone CRM",
        )
        crm_status = "PASS" if crm.get("ok") else "FAIL"
        crm_id = str((crm.get("output") or {}).get("id") or "")
        steps.append({"step": "crm_upsert", "status": crm_status, "note": crm_id or str(crm.get("error"))})
        if not crm.get("ok"):
            print(json.dumps({"ok": False, "steps": steps}))
            return 1

        session = runtime.session_factory()
        try:
            report = build_brain_capability_report(session=session, tenant_id=tenant_id)
            m11 = next(item for item in report.missions if item.mission_id == "M11")
        finally:
            session.close()

        if m11.status == "BLOCKED":
            print(json.dumps({"ok": False, "steps": steps, "m11_status": m11.status, "m11_note": m11.note}))
            return 1

        print(
            json.dumps(
                {
                    "ok": True,
                    "artifact_id": artifact_id,
                    "steps": steps,
                    "m11_status": m11.status,
                    "m11_note": m11.note,
                    "llm_ready": settings.llm_ready,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        runtime.dispose()


if __name__ == "__main__":
    raise SystemExit(main())