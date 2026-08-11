from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.db.tenant_session import activate_tenant_session
from backend.services.knowledge.knowledge_ledger import record_knowledge_qualification
from backend.services.ontology.knowledge_qualification import KnowledgeQualificationResult
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    SideEffectClass,
    ToolInvocation,
)


class RecordKnowledgeQualificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: KnowledgeQualificationResult


def knowledge_record_qualification(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = RecordKnowledgeQualificationInput.model_validate(invocation.input)
    if payload.result.proposition is None:
        write = record_knowledge_qualification(
            cast(Session, _NoMutationSession()), tenant_id=context.tenant_id, result=payload.result
        )
    else:
        if context.session_factory is None:
            raise RuntimeError("knowledge persistence requires a primary session factory")
        session = context.session_factory()
        try:
            activate_tenant_session(session, context.tenant_id)
            write = record_knowledge_qualification(session, tenant_id=context.tenant_id, result=payload.result)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    output = write.model_dump(mode="json")
    output.update({"qualification_status": payload.result.status.value, "algorithm": payload.result.algorithm})
    changed: list[str] = []
    if write.qualification_created and write.qualification_record_id:
        changed.append(f"knowledge_qualification:{write.qualification_record_id}")
    if write.artifact_created and write.artifact_record_id:
        changed.append(f"knowledge_artifact:{write.artifact_record_id}")
    summary = f"Knowledge qualification persistence: {write.status.value}"
    evidence = EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="knowledge_ledger",
        action_name="knowledge.record_qualification",
        tool_provider="ajenda_knowledge",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=output,
        records_changed=changed,
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
    )
    return ActionResult(
        action="knowledge.record_qualification",
        provider="ajenda_knowledge",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=output,
        evidence=[evidence],
        records_changed=changed,
        summary=summary,
    )


class _NoMutationSession:
    """Sentinel proving proposition-less results cannot access persistence."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"ineligible qualification attempted session operation {name}")


def register_knowledge_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="knowledge.record_qualification",
            handler=knowledge_record_qualification,
            provider="ajenda_knowledge",
            input_model=RecordKnowledgeQualificationInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
