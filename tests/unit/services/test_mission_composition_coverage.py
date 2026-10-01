from __future__ import annotations

from backend.services.mission_composition.coverage import assess_coverage
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.service import MissionCompositionService


def _intent(instruction: str):
    return interpret_instruction(instruction)


def test_supported_fixture_scope_reports_capacity() -> None:
    assessment = assess_coverage(
        _intent("Find five software development companies in Austin using local fixture data only.")
    )

    assert assessment.status == "supported_with_limits"
    assert assessment.mode == "local_fixture"
    assert assessment.available_quantity == 5
    assert assessment.ready is True


def test_unsupported_fixture_scope_blocks_before_runtime() -> None:
    assessment = assess_coverage(_intent("Find five dental companies in Austin using local fixture data only."))

    assert assessment.status == "unsupported_scope"
    assert assessment.available_quantity == 0
    assert assessment.ready is False


def test_fixture_quantity_over_capacity_blocks_without_inventing_records() -> None:
    assessment = assess_coverage(_intent("Find five HVAC companies in Dallas using local fixture data only."))

    assert assessment.status == "insufficient_capacity"
    assert assessment.available_quantity == 3
    assert assessment.ready is False


def test_public_and_internal_sources_remain_unknown_until_runtime_observation() -> None:
    public = assess_coverage(_intent("Find five HVAC companies in Dallas."))
    internal = assess_coverage(_intent("Review five companies from Ajenda internal CRM records."))

    assert public.status == "unknown"
    assert internal.status == "unknown"
    assert public.ready is True
    assert internal.ready is True


def test_composition_record_exposes_coverage_without_granting_authority() -> None:
    record = MissionCompositionService(db=None).compose(
        tenant_id="tenant-coverage",
        instruction="Find five dental companies in Austin using local fixture data only.",
    )

    assert record.coverage_assessment is not None
    assert record.coverage_assessment.status == "unsupported_scope"
    assert record.ready_to_start is False
    assert record.coverage_assessment.grants_execution_authority is False
