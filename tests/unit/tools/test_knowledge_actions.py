from uuid import uuid4

import pytest

from backend.services.ontology.knowledge_qualification import qualify_pattern_knowledge
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, SideEffectClass, ToolInvocation
from tests.unit.ontology.test_knowledge_qualification import candidate


def _context(*, session_factory=None) -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id="tenant-A",
        task_id=uuid4(),
        worker_id="worker",
        lease_id="lease",
        session_factory=session_factory,
    )


def test_knowledge_action_is_registered_as_governed_internal_write() -> None:
    definition = get_default_action_registry(rebuild=True).get("knowledge.record_qualification")
    assert definition.provider == "ajenda_knowledge"
    assert definition.side_effect_class == SideEffectClass.INTERNAL_WRITE


def test_knowledge_action_fails_closed_without_primary_session_factory() -> None:
    result = qualify_pattern_knowledge(candidate())
    invocation = ToolInvocation(
        action="knowledge.record_qualification", input={"result": result.model_dump(mode="json")}
    )

    with pytest.raises(RuntimeError, match="primary session factory"):
        get_default_action_registry(rebuild=True).invoke(invocation, _context())


def test_propositionless_result_is_reported_ineligible_without_session() -> None:
    result = qualify_pattern_knowledge(candidate().model_copy(update={"semantic_context": None}))
    invocation = ToolInvocation(
        action="knowledge.record_qualification", input={"result": result.model_dump(mode="json")}
    )

    action_result = get_default_action_registry(rebuild=True).invoke(invocation, _context())

    assert action_result.output["status"] == "not_ledger_eligible"
    assert action_result.output["persistence_committed"] is False
    assert action_result.records_changed == []
    assert action_result.evidence[0].evidence_type == "action_result_evidence"
