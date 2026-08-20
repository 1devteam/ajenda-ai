from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.services.mission_composition.contracts import CompositionProvenance
from backend.services.mission_composition.vertical_know_how import (
    REVOPS_V1_KNOW_HOW,
    DeliverableField,
    KnowHowBudget,
    KnowHowStage,
    VerticalKnowHowContract,
    get_vertical_know_how,
    select_vertical_know_how,
    validate_know_how_runtime_references,
)
from backend.services.tools.action_registry import ActionRegistry


def _payload() -> dict[str, object]:
    return REVOPS_V1_KNOW_HOW.model_dump(mode="python")


def test_revops_know_how_is_declarative_versioned_and_promotion_blocked() -> None:
    assert REVOPS_V1_KNOW_HOW.authority_class == "declarative"
    assert REVOPS_V1_KNOW_HOW.grants_execution_authority is False
    assert REVOPS_V1_KNOW_HOW.know_how_version == "1.0.0"
    assert REVOPS_V1_KNOW_HOW.promotion_status == "blocked_pending_owner_thresholds"
    assert REVOPS_V1_KNOW_HOW.budget is None


def test_revops_know_how_resolves_runtime_actions_and_schemas() -> None:
    validate_know_how_runtime_references(REVOPS_V1_KNOW_HOW)


def test_revops_know_how_fails_closed_when_runtime_action_is_unavailable() -> None:
    registry = ActionRegistry()
    registry.freeze()
    with pytest.raises(ValueError, match="unknown action"):
        validate_know_how_runtime_references(REVOPS_V1_KNOW_HOW, registry=registry)


def test_know_how_version_lookup_fails_closed() -> None:
    assert (
        get_vertical_know_how(
            know_how_id=REVOPS_V1_KNOW_HOW.know_how_id,
            know_how_version=REVOPS_V1_KNOW_HOW.know_how_version,
        )
        is REVOPS_V1_KNOW_HOW
    )
    with pytest.raises(ValueError, match="unknown or unavailable"):
        get_vertical_know_how(know_how_id=REVOPS_V1_KNOW_HOW.know_how_id, know_how_version="2.0.0")


def test_composition_provenance_rejects_partial_know_how_reference() -> None:
    with pytest.raises(ValidationError, match="requires both id and version"):
        CompositionProvenance(know_how_id=REVOPS_V1_KNOW_HOW.know_how_id)


def test_know_how_selection_is_bounded_to_revops_outcomes() -> None:
    assert select_vertical_know_how(["research_prospects", "prepare_outreach"]) is REVOPS_V1_KNOW_HOW
    assert select_vertical_know_how(["publish_content"]) is None
    assert select_vertical_know_how(["research_prospects", "publish_content"]) is None


def test_eligible_know_how_requires_owner_approved_budget() -> None:
    payload = _payload()
    payload["promotion_status"] = "eligible"
    with pytest.raises(ValidationError, match="owner-approved budget"):
        VerticalKnowHowContract.model_validate(payload)

    payload["budget"] = KnowHowBudget(
        max_prospects=5,
        max_external_effects=5,
        max_wall_seconds=600,
        max_provider_calls=30,
        max_model_tokens=50_000,
        max_cost_usd=10,
    )
    assert VerticalKnowHowContract.model_validate(payload).promotion_status == "eligible"


def test_know_how_rejects_unknown_job() -> None:
    payload = _payload()
    stages = list(REVOPS_V1_KNOW_HOW.stages)
    stages[0] = stages[0].model_copy(update={"job_keys": ("research.unknown",)})
    payload["stages"] = stages
    with pytest.raises(ValidationError, match="unknown jobs"):
        VerticalKnowHowContract.model_validate(payload)


def test_know_how_rejects_cycle() -> None:
    payload = _payload()
    stages = list(REVOPS_V1_KNOW_HOW.stages)
    stages[0] = stages[0].model_copy(update={"depends_on": ("draft",)})
    payload["stages"] = stages
    with pytest.raises(ValidationError, match="cycle"):
        VerticalKnowHowContract.model_validate(payload)


def test_know_how_rejects_missing_deliverable_producer() -> None:
    payload = _payload()
    fields = list(REVOPS_V1_KNOW_HOW.deliverable_fields)
    fields.append(DeliverableField(field_key="unproduced", produced_by_jobs=("email.prepare_outreach",)))
    payload["deliverable_fields"] = fields
    with pytest.raises(ValidationError, match="no declared producer"):
        VerticalKnowHowContract.model_validate(payload)


def test_external_effect_stage_requires_review_boundary() -> None:
    payload = _payload()
    stages = [
        stage.model_copy(update={"review_boundary": "none"}) if stage.stage_key == "delivery" else stage
        for stage in REVOPS_V1_KNOW_HOW.stages
    ]
    payload["stages"] = stages
    contract = VerticalKnowHowContract.model_validate(payload)
    with pytest.raises(ValueError, match="lacks review boundary"):
        validate_know_how_runtime_references(contract)


def test_know_how_rejects_duplicate_job_ownership() -> None:
    payload = _payload()
    stages = list(REVOPS_V1_KNOW_HOW.stages)
    stages.append(KnowHowStage(stage_key="duplicate", job_keys=("email.prepare_outreach",), depends_on=("draft",)))
    payload["stages"] = stages
    with pytest.raises(ValidationError, match="exactly one stage"):
        VerticalKnowHowContract.model_validate(payload)
