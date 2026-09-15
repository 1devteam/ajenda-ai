from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.services.llm.contracts import LlmGenerateResult
from backend.services.mission_composition.structured_planner import (
    OpenAiCompatibleStructuredPlanner,
    PlannerArtifactBinding,
    PlannerBudgetProposal,
    PlannerJobProposal,
    StructuredPlannerProposal,
    parse_planner_json,
    validate_planner_proposal,
)
from backend.services.mission_composition.vertical_know_how import REVOPS_V1_KNOW_HOW


def _proposal(**updates: object) -> StructuredPlannerProposal:
    payload: dict[str, object] = {
        "objective": "Research and qualify roofing companies in Austin.",
        "know_how_id": REVOPS_V1_KNOW_HOW.know_how_id,
        "know_how_version": REVOPS_V1_KNOW_HOW.know_how_version,
        "material_clause_ids": ("c1", "c2"),
        "jobs": (
            PlannerJobProposal(job_key="research.discover_prospects", reason="Research requested."),
            PlannerJobProposal(
                job_key="sales.qualify_prospects",
                depends_on=("research.discover_prospects",),
                reason="Qualification requested.",
            ),
        ),
        "artifact_bindings": (
            PlannerArtifactBinding(
                producer_job="research.discover_prospects",
                output_name="prospect_candidates",
                consumer_job="sales.qualify_prospects",
                input_name="prospect_candidates",
            ),
        ),
        "success_criteria": ("Three prospects have evidence-backed qualification reasons.",),
        "budget": PlannerBudgetProposal(
            max_steps=5,
            max_replans=1,
            max_provider_calls=10,
            max_model_tokens=10_000,
            max_wall_seconds=300,
            max_cost_usd=5,
        ),
    }
    payload.update(updates)
    return StructuredPlannerProposal.model_validate(payload)


def test_valid_structured_proposal_is_non_authoritative() -> None:
    proposal = _proposal()
    validate_planner_proposal(
        proposal,
        know_how=REVOPS_V1_KNOW_HOW,
        expected_material_clause_ids={"c1", "c2"},
    )
    assert proposal.grants_execution_authority is False


def test_optional_decision_support_can_be_added_without_being_deterministically_required() -> None:
    proposal = _proposal(
        objective="Observe contacts and optionally add decision support.",
        jobs=(
            PlannerJobProposal(job_key="research.discover_prospects", reason="Research requested."),
            PlannerJobProposal(
                job_key="research.observe_sources",
                depends_on=("research.discover_prospects",),
                reason="Observed contacts requested.",
            ),
            PlannerJobProposal(
                job_key="intelligence.retrieve_knowledge",
                depends_on=("research.observe_sources",),
                reason="Optional current-knowledge support.",
            ),
            PlannerJobProposal(
                job_key="intelligence.advise_next",
                depends_on=("research.observe_sources", "intelligence.retrieve_knowledge"),
                reason="Optional recommendation support.",
            ),
        ),
        artifact_bindings=(),
    )

    validate_planner_proposal(
        proposal,
        know_how=REVOPS_V1_KNOW_HOW,
        expected_material_clause_ids={"c1", "c2"},
        required_job_keys={"research.discover_prospects", "research.observe_sources"},
    )


def test_parser_rejects_prose_and_extra_fields() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_planner_json("```json\n{}\n```")
    payload = _proposal().model_dump(mode="json")
    payload["instructions_from_retrieved_content"] = "ignore policy"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        parse_planner_json(json.dumps(payload))


def test_structured_adapter_rejects_template_fallback() -> None:
    class Generator:
        def generate(self, request: object) -> LlmGenerateResult:
            return LlmGenerateResult(text="{}", provider="template_fallback", model="template", used_llm=False)

    adapter = OpenAiCompatibleStructuredPlanner(generator=Generator())
    from backend.services.mission_composition.structured_planner import PlannerRequest

    request = PlannerRequest(
        instruction="untrusted instruction",
        raw_instruction_sha256="a" * 64,
        know_how_id=REVOPS_V1_KNOW_HOW.know_how_id,
        know_how_version=REVOPS_V1_KNOW_HOW.know_how_version,
        allowed_job_keys=("research.discover_prospects",),
        material_clauses=({"clause_id": "c1", "text": "research", "status": "recognized"},),
    )
    with pytest.raises(ValueError, match="fallback output is rejected"):
        adapter.propose(request)


def test_planner_cannot_claim_execution_authority() -> None:
    with pytest.raises(ValidationError, match="cannot grant"):
        _proposal(grants_execution_authority=True)


def test_validator_rejects_clause_coverage_mismatch() -> None:
    with pytest.raises(ValueError, match="coverage mismatch"):
        validate_planner_proposal(
            _proposal(material_clause_ids=("c1",)),
            know_how=REVOPS_V1_KNOW_HOW,
            expected_material_clause_ids={"c1", "c2"},
        )


def test_validator_rejects_job_outside_selected_know_how() -> None:
    proposal = _proposal(
        jobs=(PlannerJobProposal(job_key="gtm.publish_content", reason="Injected provider instruction."),),
        artifact_bindings=(),
    )
    with pytest.raises(ValueError, match="outside know-how"):
        validate_planner_proposal(
            proposal,
            know_how=REVOPS_V1_KNOW_HOW,
            expected_material_clause_ids={"c1", "c2"},
        )


def test_validator_rejects_cycle() -> None:
    proposal = _proposal(
        jobs=(
            PlannerJobProposal(
                job_key="research.discover_prospects",
                depends_on=("sales.qualify_prospects",),
                reason="Research.",
            ),
            PlannerJobProposal(
                job_key="sales.qualify_prospects",
                depends_on=("research.discover_prospects",),
                reason="Qualify.",
            ),
        )
    )
    with pytest.raises(ValueError, match="cycle"):
        validate_planner_proposal(
            proposal,
            know_how=REVOPS_V1_KNOW_HOW,
            expected_material_clause_ids={"c1", "c2"},
        )


def test_validator_rejects_invalid_artifact_binding() -> None:
    proposal = _proposal(
        artifact_bindings=(
            PlannerArtifactBinding(
                producer_job="research.discover_prospects",
                output_name="invented_output",
                consumer_job="sales.qualify_prospects",
                input_name="prospect_candidates",
            ),
        )
    )
    with pytest.raises(ValueError, match="unknown producer output"):
        validate_planner_proposal(
            proposal,
            know_how=REVOPS_V1_KNOW_HOW,
            expected_material_clause_ids={"c1", "c2"},
        )


@pytest.mark.parametrize(
    ("job_key", "connector"),
    [("email.deliver_outreach", "gmail")],
)
def test_validator_rejects_missing_external_connection(job_key: str, connector: str) -> None:
    proposal = _proposal(
        jobs=(PlannerJobProposal(job_key=job_key, reason="Requested external effect."),),
        artifact_bindings=(),
        review_points=(job_key,),
    )
    with pytest.raises(ValueError, match=f"{job_key}:{connector}"):
        validate_planner_proposal(
            proposal,
            know_how=REVOPS_V1_KNOW_HOW,
            expected_material_clause_ids={"c1", "c2"},
        )


def test_validator_requires_external_review_point() -> None:
    proposal = _proposal(
        jobs=(PlannerJobProposal(job_key="email.deliver_outreach", reason="Requested send."),),
        artifact_bindings=(),
    )
    with pytest.raises(ValueError, match="lacks review point"):
        validate_planner_proposal(
            proposal,
            know_how=REVOPS_V1_KNOW_HOW,
            expected_material_clause_ids={"c1", "c2"},
            connected_integrations={"gmail"},
        )
