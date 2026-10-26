"""Governed runtime handoff from a canonical source read into Business Understanding.

The action accepts a source EvidenceRecord identity, never caller-authored KPI
values. Its side effect is authorized by the existing runtime owner before
this handler is invoked; the handler itself cannot approve or schedule work.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.db.tenant_session import activate_tenant_session
from backend.repositories.business_understanding_repository import BusinessUnderstandingRepository
from backend.services.business_understanding.service import BusinessUnderstandingService
from backend.services.tools.action_registry_contracts import ActionDefinition, ActionRegistryPort
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    SideEffectClass,
    ToolInvocation,
)


class IngestRuntimeMeasurementInput(BaseModel):
    """Identity-only input; the canonical source owns all commercial values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_evidence_id: uuid.UUID


def business_ingest_runtime_measurement(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    """Persist one already verified source snapshot and read back the owner row."""

    payload = IngestRuntimeMeasurementInput.model_validate(invocation.input)
    if context.session_factory is None:
        raise RuntimeError("runtime measurement ingestion requires a primary session factory")
    session: Session = context.session_factory()
    try:
        activate_tenant_session(session, context.tenant_id)
        measurement, need = BusinessUnderstandingService(session).ingest_runtime_record_measurement(
            tenant_id=context.tenant_id,
            source_evidence_id=payload.source_evidence_id,
            producer="business.ingest_runtime_measurement",
        )
        persisted = BusinessUnderstandingRepository(session).get_measurement_for_tenant(
            tenant_id=context.tenant_id, measurement_id=measurement.id
        )
        if (
            persisted is None
            or persisted.source_kind != "source_verified"
            or persisted.source_content_fingerprint != measurement.source_content_fingerprint
            or persisted.source_reference.get("evidence_id") is None
        ):
            raise ValueError("runtime measurement readback disagrees with persisted source owner")
        output = {
            "source_evidence_id": str(payload.source_evidence_id),
            "measurement_id": str(persisted.id),
            "source_kind": persisted.source_kind,
            "source_version": persisted.source_version,
            "source_content_fingerprint": persisted.source_content_fingerprint,
            "need_id": need.need_id if need is not None else None,
            "need_revision": need.revision if need is not None else None,
            "source_independence_established": False,
            "kpi_truth_independently_verified": False,
            "limitations": persisted.limitations,
        }
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    inspected = [f"evidence:{payload.source_evidence_id}"]
    # The measurement ID is stable under retries. A durable output is a proof
    # of owner admission, not an assertion that the row was freshly inserted.
    admitted = [f"business_measurement:{output['measurement_id']}"]
    summary = f"Admitted canonical source-backed measurement {output['measurement_id']}."
    evidence = EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="business_measurement_ingress",
        action_name="business.ingest_runtime_measurement",
        tool_provider="ajenda_business_understanding",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id is not None else None,
        summary=summary,
        structured_payload=output,
        records_inspected=inspected,
        records_changed=admitted,
        limitations=["source_independence_not_established", "source_read_proved_not_kpi_truth"],
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> BusinessUnderstandingService",
            "evidence_role": "runtime_measurement_ingress",
        },
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
    )
    return ActionResult(
        action="business.ingest_runtime_measurement",
        provider="ajenda_business_understanding",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=output,
        evidence=[evidence],
        records_inspected=inspected,
        records_changed=admitted,
        summary=summary,
        limitations=["source_independence_not_established", "source_read_proved_not_kpi_truth"],
    )


def register_business_measurement_actions(registry: ActionRegistryPort) -> None:
    """Register an approval-required write through the shared runtime spine."""

    registry.register(
        ActionDefinition(
            name="business.ingest_runtime_measurement",
            handler=business_ingest_runtime_measurement,
            provider="ajenda_business_understanding",
            input_model=IngestRuntimeMeasurementInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
