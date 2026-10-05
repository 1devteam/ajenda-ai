from backend.services.mission_composition.contracts import Contradiction
from backend.services.mission_composition.coverage import assess_coverage
from backend.services.mission_composition.epistemic import build_epistemic_context
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.service import MissionCompositionService


def test_fixture_context_is_explicit_and_not_runtime_observed() -> None:
    intent = interpret_instruction("Find five software development companies in Austin using local fixture data only.")
    context = build_epistemic_context(intent, assess_coverage(intent))

    assert "explicit_user" in context.source_classes
    assert "local_fixture" in context.source_classes
    assert context.freshness == "not_observed"
    assert context.grants_execution_authority is False
    assert context.confidence_semantics == "policy_estimate"
    assert context.budget.estimate_semantics == "policy_estimate"
    assert context.budget.calibration_reference == "uncalibrated_policy_v1"


def test_external_context_requires_runtime_observation() -> None:
    intent = interpret_instruction("Find five HVAC companies in Dallas.")
    context = build_epistemic_context(intent, assess_coverage(intent))

    assert "public_observation" in context.source_classes
    assert "runtime_source_observation" in context.required_evidence
    assert "runtime_source_observation" in context.missing_evidence
    assert context.budget.tolerance == "standard"
    assert context.budget_status == "within_budget"


def test_unresolved_contradictions_are_visible() -> None:
    intent = interpret_instruction("Find five companies in Austin.").model_copy(
        update={
            "contradictions": [
                Contradiction(
                    field_path="target_entities.location",
                    first_span="in Austin",
                    second_span="not in Austin",
                    first_value="Austin",
                    second_value="not Austin",
                )
            ]
        }
    )
    context = build_epistemic_context(intent, assess_coverage(intent))

    assert context.contradiction_status == "unresolved"
    assert context.unresolved_contradiction_count >= 1
    assert "contradiction_resolution" in context.missing_evidence
    assert context.budget_status == "exceeded"
    assert any("unresolved_contradictions" in item for item in context.budget_excesses)


def test_supported_fixture_uses_strict_zero_missing_evidence_budget() -> None:
    intent = interpret_instruction("Find five software development companies in Austin using local fixture data only.")
    context = build_epistemic_context(intent, assess_coverage(intent))

    assert context.budget.tolerance == "strict"
    assert context.budget.max_missing_evidence == 0
    assert context.budget_status == "within_budget"


def test_composition_record_contains_epistemic_context() -> None:
    record = MissionCompositionService(db=None).compose(
        tenant_id="tenant-epistemic",
        instruction="Find five HVAC companies in Dallas.",
    )

    assert record.epistemic_context is not None
    assert record.epistemic_context.freshness == "not_observed"
    assert record.epistemic_context.grants_execution_authority is False
