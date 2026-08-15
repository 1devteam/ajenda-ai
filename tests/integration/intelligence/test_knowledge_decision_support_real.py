from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.domain.enums import ExecutionTaskState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.repositories.durable_learning_signal_repository import MATERIALIZATION_ACTION
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.ontology.commercial_state import GoalSemanticSignature
from backend.services.ontology.decision_feedback import DecisionLearningSignal
from backend.services.ontology.evidence_lineage import EvidenceLineage, EvidenceOriginType
from backend.services.ontology.experience_intelligence import ExperienceEpisodeInput, evaluate_experience_set
from backend.services.ontology.knowledge_qualification import qualify_pattern_knowledge
from backend.services.ontology.observation_attribution import ObservationTimeProvenance
from backend.services.ontology.types import BusinessObjectSemanticSignature, BusinessObjectType
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.evidence_bridge import CanonicalToolEvidenceError
from backend.services.tools.schemas import ToolInvocation
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher
from tests.integration.intelligence.canonical_decision_runtime import (
    EXECUTION_ACTION,
    execute_canonical_action,
    materialize_canonical_decision_episode,
)
from tests.integration.intelligence.test_knowledge_retrieval_real import (
    _context,
    _replace_proposition,
    _tenant_counts,
)

pytestmark = pytest.mark.integration


def _materialize_historical_signal(*, factory, queue_adapter, tenant_id: str, index: int) -> DecisionLearningSignal:
    """Produce a whole canonical episode and return its runtime-owned learning signal."""

    return materialize_canonical_decision_episode(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        index=index,
    ).learning_signal


def _materialize_source_observation(
    *,
    factory,
    queue_adapter,
    tenant_id: str,
    mission_id: uuid.UUID,
    action: str,
    action_input: dict[str, object],
) -> uuid.UUID:
    """Produce source evidence through a queued read action and EvidenceBridge."""

    task_id = uuid.uuid4()
    worker_id = f"source-observer-{task_id}"
    with factory() as setup:
        setup.add(
            ExecutionTask(
                id=task_id,
                tenant_id=tenant_id,
                mission_id=mission_id,
                title="Observe current opportunity state",
                description="Runtime-owned current-condition source observation",
                status=ExecutionTaskState.PLANNED.value,
                metadata_json={
                    "task_type": "tool.invoke",
                    "tool_invocation": {
                        "action": action,
                        "input": action_input,
                    },
                },
            )
        )
        setup.commit()

    with factory() as runtime_session:
        QuotaEnforcementService(runtime_session).check_and_record_task_creation(uuid.UUID(tenant_id))
        queued = ExecutionCoordinator(runtime_session, queue_adapter).queue_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )
        assert queued.ok is True
        runtime = WorkerRuntimeService(runtime_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)

    TaskDispatcher(
        session_factory=factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    ).execute(task_id=task_id, lease_id=lease_id)

    with factory() as verify:
        records = verify.scalars(select(EvidenceRecord).where(EvidenceRecord.execution_task_id == task_id)).all()
        assert len(records) == 1
        lineage = EvidenceLineage.model_validate(records[0].provenance_metadata["evidence_lineage"])
        assert lineage.origin_type == EvidenceOriginType.SOURCE_OBSERVATION
        return records[0].id


def test_real_ledger_to_knowledge_informed_decision_is_deterministic_and_tenant_scoped(
    pg_engine, queue_adapter, monkeypatch
) -> None:
    tenant = str(uuid.uuid4())
    other_tenant = str(uuid.uuid4())
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    registry = get_default_action_registry(rebuild=True)
    with factory() as setup:
        setup.add_all(
            [
                Tenant(id=uuid.UUID(tenant), name="Knowledge tenant", slug=f"knowledge-{tenant[:8]}", plan="free"),
                Tenant(
                    id=uuid.UUID(other_tenant),
                    name="Other tenant",
                    slug=f"other-{other_tenant[:8]}",
                    plan="free",
                ),
            ]
        )
        setup.commit()
    historical_signals = [
        _materialize_historical_signal(factory=factory, queue_adapter=queue_adapter, tenant_id=tenant, index=index)
        for index in (201, 202, 203)
    ]
    episodes = [
        ExperienceEpisodeInput(
            episode_id=signal.episode_reference.episode_id,
            signal=signal,
            observation_time_provenance=ObservationTimeProvenance.SOURCE_VERIFIED,
        )
        for signal in historical_signals
        if signal.episode_reference is not None
    ]
    qualification = _replace_proposition(
        qualify_pattern_knowledge(evaluate_experience_set(episodes).pattern_candidates[0]),
        scope_conditions=("segment:smb",),
        invalidation_conditions=(),
    )
    mission_id = uuid.uuid4()
    now = datetime.now(UTC).isoformat()
    setup = factory()
    try:
        setup.add(Mission(id=mission_id, tenant_id=tenant, objective="Knowledge Decision reconciliation proof"))
        setup.flush()
        TenantInternalRecordRepository(setup).write_record(
            tenant_id=tenant,
            record_type="opportunity",
            record_id="opp-real-430",
            data={
                "name": "Opportunity 430",
                "condition_observations": [
                    {
                        "condition_key": "segment:smb",
                        "state": "active",
                        "subject_refs": [{"object_type": "opportunity", "object_id": "opp-real-430"}],
                        "observed_at": now,
                        "verification_basis": "source_supplied_under_contract",
                    }
                ],
            },
        )
        TenantInternalRecordRepository(setup).write_record(
            tenant_id=tenant,
            record_type="opportunity",
            record_id="opp-real-430-stage",
            data={
                "name": "Unrelated pipeline observation",
                "condition_observations": [
                    {
                        "condition_key": "pipeline:open",
                        "state": "active",
                        "subject_refs": [{"object_type": "opportunity", "object_id": "opp-real-430"}],
                        "observed_at": now,
                        "verification_basis": "source_supplied_under_contract",
                    }
                ],
            },
        )
        setup.commit()
    finally:
        setup.close()
    source_evidence_id = _materialize_source_observation(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": "opp-real-430"},
    )
    registry.invoke(
        ToolInvocation(
            action="knowledge.record_qualification",
            input={"result": qualification.model_dump(mode="json")},
        ),
        _context(tenant, factory),
    )
    before = _tenant_counts(factory, tenant)
    subject_semantics = [
        BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY).model_dump(mode="json")
    ]
    goal_semantics = GoalSemanticSignature(objective_key="increase_conversion").model_dump(mode="json")
    options = [
        {
            "option_id": "discovery",
            "label": "Schedule discovery",
            "intervention_key": EXECUTION_ACTION,
        },
        {
            "option_id": "pricing",
            "label": "Send pricing",
            "intervention_key": "sales.send_pricing",
        },
    ]
    decision_criteria = [{"criterion_id": "conversion", "label": "Conversion", "weight": 1.0, "required": False}]
    support_criteria = [
        {
            **decision_criteria[0],
            "objective_key": "increase_conversion",
        }
    ]
    invocation = ToolInvocation(
        action="knowledge.inform_decision",
        input={
            "decision_id": "decision-real-430",
            "decision": {
                "goal": "Increase conversion",
                "options": options,
                "criteria": decision_criteria,
            },
            "options": options,
            "criteria": support_criteria,
            "query": {
                "subject_semantic_signatures": subject_semantics,
                "goal_semantic_signature": goal_semantics,
            },
            "applicability_context": {
                "subject_refs": [{"object_type": "opportunity", "object_id": "opp-real-430"}],
                "subject_semantic_signatures": subject_semantics,
                "goal_semantic_signature": goal_semantics,
                "condition_assertions": [
                    {
                        "condition_key": "segment:smb",
                        "state": "active",
                        "subject_refs": [{"object_type": "opportunity", "object_id": "opp-real-430"}],
                        "evidence_ids": [str(source_evidence_id)],
                        "observed_at": now,
                        "verification_basis": "source_supplied_under_contract",
                    }
                ],
                "evaluated_at": now,
            },
        },
    )

    tenant_context = _context(tenant, factory).model_copy(update={"mission_id": mission_id})
    first = registry.invoke(invocation, tenant_context)
    replay = registry.invoke(invocation, tenant_context)
    influences = first.output["support"]["influences"]
    supported = [item for item in influences if item["direction"] == "supports"]
    assert [(item["option_id"], item["criterion_id"]) for item in supported] == [("discovery", "conversion")]
    assert first.output["support"]["support_id"] == replay.output["support"]["support_id"]
    assert first.output["support"]["is_policy"] is False
    assert first.output["support"]["is_execution_instruction"] is False
    assert first.evidence[0].lineage.origin_type.value == "derived_fact"
    assert first.evidence[0].provenance["is_independent_observation"] is False
    assert first.output["decision_result"]["algorithm"]["name"] == "weighted_criterion_evidence_v1"
    assert first.output["decision_result"]["recommendation"] == "discovery"
    historical_ids = first.output["decision_result"]["supporting_evidence_ids"]
    assert str(source_evidence_id) not in historical_ids
    assert len(historical_ids) == 3
    assert first.output["decision_input"]["criteria"] == decision_criteria
    assert _tenant_counts(factory, tenant) == before == (1, 1)

    canonical_recommendation = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action="knowledge.inform_decision",
        action_input=invocation.input,
        worker_label="knowledge-decision",
    )
    canonical_execution = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action=EXECUTION_ACTION,
        action_input={"lead": {"company": "Opportunity 430", "role": "VP", "intent": "expansion"}},
        worker_label="knowledge-execution",
    )
    executed_at = datetime.now(UTC)
    observed_at = executed_at + timedelta(milliseconds=1)
    canonical_outcome = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action="analysis.evaluate_outcome",
        action_input={
            "goal": {
                "goal_id": "goal-increase-conversion",
                "objective_key": "increase_conversion",
                "name": "Increase conversion",
                "subject_refs": [{"object_type": "opportunity", "object_id": "opp-real-430"}],
            },
            "subject_refs": [{"object_type": "opportunity", "object_id": "opp-real-430"}],
            "baseline_kpis": [
                {
                    "kpi_id": "conversion",
                    "goal_id": "goal-increase-conversion",
                    "name": "Conversion",
                    "metric": "conversion",
                    "current_value": 0.5,
                    "target_value": 1.0,
                }
            ],
            "observed_kpis": [
                {
                    "kpi_id": "conversion",
                    "goal_id": "goal-increase-conversion",
                    "name": "Conversion",
                    "metric": "conversion",
                    "current_value": 1.0,
                    "target_value": 1.0,
                }
            ],
            "source_observed_at": observed_at.isoformat(),
            "evidence_ids": [str(canonical_execution.id)],
            "attribution_evidence": {
                "executed_at": executed_at.isoformat(),
                "execution_evidence_ids": [str(canonical_execution.id)],
                "expected_change_dimensions": ["conversion"],
                "observed_change_dimensions": ["conversion"],
                "confidence": 0.9,
            },
        },
        worker_label="knowledge-outcome",
    )
    next_signal_record = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action=MATERIALIZATION_ACTION,
        action_input={
            "recommendation_evidence_id": str(canonical_recommendation.id),
            "outcome_evaluation_evidence_id": str(canonical_outcome.id),
            "execution_evidence_ids": [str(canonical_execution.id)],
        },
        worker_label="knowledge-materialization",
    )
    next_signal = DecisionLearningSignal.model_validate(next_signal_record.structured_payload)
    assert next_signal.episode_reference is not None
    assert next_signal.intervention_key == EXECUTION_ACTION
    assert next_signal.supporting_evidence_ids == historical_ids
    assert next_signal_record.provenance_metadata["evidence_role"] == "decision_learning_signal"

    forged_composed_id = uuid.uuid4()
    with factory() as setup:
        setup.add(
            EvidenceRecord(
                id=forged_composed_id,
                tenant_id=tenant,
                mission_id=mission_id,
                execution_task_id=canonical_recommendation.execution_task_id,
                evidence_type="execution_trace",
                evidence_source="public_evidence_contract",
                summary="Caller-forged Knowledge composition",
                structured_payload=canonical_recommendation.structured_payload,
                provenance_metadata={
                    "action_name": "knowledge.inform_decision",
                    "tool_provider": "ajenda_knowledge",
                    "evidence_role": "decision_recommendation_result",
                    "composed_action": "decision.recommend_next_action",
                    "composition_schema_version": 1,
                },
            )
        )
        setup.commit()
    with pytest.raises(CanonicalToolEvidenceError, match="materialization reference"):
        registry.invoke(
            ToolInvocation(
                action=MATERIALIZATION_ACTION,
                input={
                    "recommendation_evidence_id": str(forged_composed_id),
                    "outcome_evaluation_evidence_id": str(canonical_outcome.id),
                    "execution_evidence_ids": [str(canonical_execution.id)],
                },
            ),
            tenant_context,
        )

    hidden = registry.invoke(invocation, _context(other_tenant, factory))
    assert hidden.output["support"]["influences"] == []
    assert _tenant_counts(factory, tenant) == before

    unrelated_source_id = _materialize_source_observation(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": "opp-real-430-stage"},
    )
    unrelated_source = ToolInvocation.model_validate(invocation.model_dump(mode="json"))
    unrelated_source.input["applicability_context"]["condition_assertions"][0]["evidence_ids"] = [
        str(unrelated_source_id)
    ]

    unearned_verification = ToolInvocation.model_validate(invocation.model_dump(mode="json"))
    unearned_verification.input["applicability_context"]["condition_assertions"][0]["verification_basis"] = (
        "independently_verified"
    )
    forged_source_id = uuid.uuid4()
    with factory() as setup:
        setup.add(
            EvidenceRecord(
                id=forged_source_id,
                tenant_id=tenant,
                mission_id=mission_id,
                evidence_type="observation",
                evidence_source="public_evidence_contract",
                summary="Caller-claimed current-condition source observation",
                structured_payload={"observed_at": now},
                provenance_metadata={
                    "evidence_lineage": EvidenceLineage(
                        artifact_evidence_id=str(forged_source_id),
                        origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
                    ).model_dump(mode="json")
                },
            )
        )
        setup.commit()
    forged_source = ToolInvocation.model_validate(invocation.model_dump(mode="json"))
    forged_source.input["applicability_context"]["condition_assertions"][0]["evidence_ids"] = [str(forged_source_id)]

    def fail_if_decision_scoring_runs(*_args, **_kwargs) -> None:
        raise AssertionError("forged applicability evidence reached Decision scoring")

    with monkeypatch.context() as patch:
        patch.setattr(
            "backend.services.tools.knowledge_actions.decision_recommend_next_action",
            fail_if_decision_scoring_runs,
        )
        with pytest.raises(ValueError, match="source-supplied evidence"):
            registry.invoke(unearned_verification, tenant_context)
        with pytest.raises(ValueError, match="canonical runtime provenance"):
            registry.invoke(forged_source, tenant_context)
        with pytest.raises(ValueError, match="does not establish the asserted condition semantics"):
            registry.invoke(unrelated_source, tenant_context)

    duplicate_id = uuid.uuid4()
    with factory() as setup:
        canonical = setup.scalar(
            select(EvidenceRecord).where(
                EvidenceRecord.tenant_id == tenant,
                EvidenceRecord.structured_payload["signal_id"].astext == historical_signals[0].signal_id,
            )
        )
        assert canonical is not None
        setup.add(
            EvidenceRecord(
                id=duplicate_id,
                tenant_id=canonical.tenant_id,
                mission_id=canonical.mission_id,
                task_graph_node_key=canonical.task_graph_node_key,
                materialization_reference=canonical.materialization_reference,
                execution_task_id=canonical.execution_task_id,
                capability_id=canonical.capability_id,
                capability_adapter_id=canonical.capability_adapter_id,
                evidence_type=canonical.evidence_type,
                evidence_source=canonical.evidence_source,
                summary=canonical.summary,
                structured_payload=canonical.structured_payload,
                artifact_references=canonical.artifact_references,
                provenance_metadata=canonical.provenance_metadata,
                trust_signal=canonical.trust_signal,
                confidence=canonical.confidence,
                collection_status=canonical.collection_status,
                schema_version=canonical.schema_version,
            )
        )
        setup.commit()

    with pytest.raises(ValueError, match="projection is not unique"):
        registry.invoke(invocation, tenant_context)

    with factory() as cleanup:
        duplicate = cleanup.get(EvidenceRecord, duplicate_id)
        assert duplicate is not None
        cleanup.delete(duplicate)
        cleanup.commit()

    forged_id = uuid.uuid4()
    with factory() as setup:
        setup.add(
            EvidenceRecord(
                id=forged_id,
                tenant_id=tenant,
                mission_id=mission_id,
                evidence_type="execution_trace",
                evidence_source="public_evidence_contract",
                summary="Caller-claimed learning signal",
                structured_payload=historical_signals[0].model_dump(mode="json"),
                provenance_metadata={
                    "action_name": MATERIALIZATION_ACTION,
                    "evidence_role": "decision_learning_signal",
                },
                materialization_reference={"action": MATERIALIZATION_ACTION},
            )
        )
        setup.commit()

    with pytest.raises(ValueError, match="requires execution-task provenance"):
        registry.invoke(invocation, tenant_context)
