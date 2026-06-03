from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from backend.api.routes.mission import MissionCreate
from backend.domain.business_profile import BusinessProfile
from backend.services.mission_brief import MissionBriefRequest, build_mission_brief


def test_mission_brief_uses_profile_defaults_without_runtime_authority() -> None:
    profile = BusinessProfile(
        id=uuid.uuid4(),
        tenant_id="tenant-a",
        approved_facts={
            "business_name": {"value": "Ajenda"},
            "allowed_actions": ["draft outreach"],
            "allowed_tools": {"values": ["crm"]},
            "evidence_expectations": ["source links"],
            "default_jurisdiction": "US-NY",
            "default_compliance_category": "marketing",
        },
    )
    request = MissionBriefRequest(
        current_intent={
            "objective": "Find qualified leads",
            "success_criteria": ["Return ten leads"],
            "allowed_actions": ["research accounts"],
        },
        request_context={"channel": "api"},
    )

    result = build_mission_brief(tenant_id="tenant-a", profile=profile, request=request)

    assert result.tenant_id == "tenant-a"
    assert result.profile_id == profile.id
    assert result.brief["profile_context"]["business_name"] == "Ajenda"
    assert result.mission_create_prefill["allowed_actions"] == ["research accounts", "draft outreach"]
    assert result.mission_create_prefill["allowed_tools"] == ["crm"]
    assert result.mission_create_prefill["compliance_category"] == "marketing"
    assert result.mission_create_prefill["jurisdiction"] == "US-NY"
    assert result.authority_flags.authority_class == "read_model"
    assert result.authority_flags.read_only is True
    assert result.authority_flags.creates_mission is False
    assert result.authority_flags.queues_work is False
    assert result.authority_flags.dispatches_workers is False
    assert result.authority_flags.writes_business_profile_truth is False


def test_current_intent_wins_when_profile_defaults_conflict() -> None:
    profile = BusinessProfile(
        tenant_id="tenant-a",
        approved_facts={
            "default_jurisdiction": "US-CO",
            "default_compliance_category": "marketing",
            "default_approval_required": True,
            "default_budget_limits": {"max_tasks": 20},
        },
    )
    request = MissionBriefRequest(
        current_intent={
            "objective": "Summarize internal notes",
            "success_criteria": ["One executive summary"],
            "jurisdiction": "US-NY",
            "compliance_category": "operational",
            "approval_required": False,
            "budget_limits": {"max_tasks": 3},
        }
    )

    result = build_mission_brief(tenant_id="tenant-a", profile=profile, request=request)

    assert result.mission_create_prefill["jurisdiction"] == "US-NY"
    assert result.mission_create_prefill["compliance_category"] == "operational"
    assert result.mission_create_prefill["approval_required"] is False
    assert result.mission_create_prefill["budget_limits"] == {"max_tasks": 3}
    assert {conflict.field for conflict in result.conflicts} == {
        "jurisdiction",
        "compliance_category",
        "approval_required",
        "budget_limits",
    }
    assert all(conflict.resolution == "current_intent_wins" for conflict in result.conflicts)


def test_missing_information_is_reported_without_fabricating_required_mission_fields() -> None:
    result = build_mission_brief(
        tenant_id="tenant-a",
        profile=None,
        request=MissionBriefRequest(current_intent={}),
    )

    missing = {item.field: item.severity for item in result.missing_information}
    assert missing["objective"] == "required"
    assert missing["success_criteria"] == "required"
    assert result.mission_create_prefill["compliance_category"] == "operational"
    assert result.mission_create_prefill["jurisdiction"] == "US-ALL"
    assert "objective" not in result.mission_create_prefill
    assert "success_criteria" not in result.mission_create_prefill


def test_mission_brief_request_rejects_oversized_or_deep_context() -> None:
    deep: dict[str, object] = {}
    cursor = deep
    for index in range(9):
        child: dict[str, object] = {}
        cursor[f"level_{index}"] = child
        cursor = child

    with pytest.raises(ValidationError):
        MissionBriefRequest(current_intent={"objective": "x"}, request_context=deep)

    with pytest.raises(ValidationError):
        MissionBriefRequest(current_intent={"budget_limits": {"unsupported": 1}})


def test_invalid_profile_defaults_are_not_emitted_as_mission_create_prefill() -> None:
    profile = BusinessProfile(
        tenant_id="tenant-a",
        approved_facts={
            "default_budget_limits": {"max_tasks": "many"},
            "default_compliance_category": "unsupported",
            "default_jurisdiction": "space",
        },
    )
    request = MissionBriefRequest(current_intent={"objective": "Plan launch", "success_criteria": ["Plan exists"]})

    result = build_mission_brief(tenant_id="tenant-a", profile=profile, request=request)

    assert "budget_limits" not in result.mission_create_prefill
    assert result.mission_create_prefill["compliance_category"] == "operational"
    assert result.mission_create_prefill["jurisdiction"] == "US-ALL"
    assert {conflict.field for conflict in result.conflicts} == {"compliance_category", "jurisdiction"}


def test_mission_brief_request_rejects_oversized_intent_list_items_before_echoing() -> None:
    long_value = "x" * 1001

    with pytest.raises(ValidationError):
        MissionBriefRequest(current_intent={"objective": "Plan launch", "success_criteria": [long_value]})

    with pytest.raises(ValidationError):
        MissionBriefRequest(
            current_intent={
                "objective": "Plan launch",
                "success_criteria": ["Plan exists"],
                "constraints": [long_value],
            }
        )


def test_mission_create_prefill_filters_success_criteria_to_mission_create_contract() -> None:
    profile = BusinessProfile(
        tenant_id="tenant-a",
        approved_facts={
            "default_success_criteria": [f"profile success {index}" for index in range(25)],
            "evidence_expectations": [f"evidence {index}" for index in range(12)],
        },
    )
    request = MissionBriefRequest(
        current_intent={"objective": "Plan launch", "success_criteria": ["valid current success"]}
    )

    result = build_mission_brief(tenant_id="tenant-a", profile=profile, request=request)

    prefill_success = result.mission_create_prefill["success_criteria"]
    assert len(prefill_success) == 20
    assert result.brief["success_criteria"] == [item["description"] for item in prefill_success]
    assert prefill_success[0]["description"] == "valid current success"
    assert all(len(item["description"]) <= 1000 for item in prefill_success)
    assert all(len(item["evidence"]) == 10 for item in prefill_success)
    MissionCreate.model_validate(result.mission_create_prefill)


def test_mission_create_prefill_filters_constraints_to_mission_create_contract() -> None:
    profile = BusinessProfile(
        tenant_id="tenant-a",
        approved_facts={"default_constraints": [f"profile constraint {index}" for index in range(25)]},
    )
    request = MissionBriefRequest(
        current_intent={
            "objective": "Plan launch",
            "success_criteria": ["Plan exists"],
            "constraints": ["valid current constraint"],
        }
    )

    result = build_mission_brief(tenant_id="tenant-a", profile=profile, request=request)

    prefill_constraints = result.mission_create_prefill["constraints"]
    assert len(prefill_constraints) == 20
    assert result.brief["constraints"] == [item["description"] for item in prefill_constraints]
    assert prefill_constraints[0] == {
        "name": "valid current constraint",
        "description": "valid current constraint",
        "hard": True,
    }
    assert all(len(item["description"]) <= 1000 for item in prefill_constraints)
    assert all(len(item["name"]) <= 120 for item in prefill_constraints)
    MissionCreate.model_validate(result.mission_create_prefill)


def test_profile_scalar_text_defaults_are_bounded_before_echoing() -> None:
    huge_value = "z" * 5001
    profile = BusinessProfile(
        tenant_id="tenant-a",
        approved_facts={
            "business_name": huge_value,
            "default_compliance_category": huge_value,
            "default_jurisdiction": huge_value,
        },
    )
    request = MissionBriefRequest(current_intent={"objective": "Plan launch", "success_criteria": ["Plan exists"]})

    result = build_mission_brief(tenant_id="tenant-a", profile=profile, request=request)

    assert "profile_context" not in result.brief
    assert result.mission_create_prefill["compliance_category"] == "operational"
    assert result.mission_create_prefill["jurisdiction"] == "US-ALL"
    assert all(huge_value != conflict.business_profile_default for conflict in result.conflicts)
