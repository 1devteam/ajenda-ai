from __future__ import annotations

from types import SimpleNamespace

from backend.services.mission_acceptance import evaluate_mission_acceptance


def _task(output: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(metadata_json={"handler_result": {"output": output}})


def test_acceptance_requires_verified_candidates_and_thresholded_qualified_records() -> None:
    met, reasons = evaluate_mission_acceptance(
        tasks=[
            _task(
                {
                    "prospect_candidates": [
                        {"company": "Unverified", "identity_status": "unverified"},
                        {"company": "Verified", "identity_status": "verified"},
                    ],
                    "qualified_prospects": [{"company": "Verified", "score_10": 8}],
                }
            )
        ],
        contract={
            "candidate_min": 2,
            "qualified_min": 2,
            "score_threshold_10": 7,
            "require_verified_identity": True,
        },
    )

    assert met is False
    assert "verified prospect identities" in " ".join(reasons)
    assert "qualified prospects scoring 7/10" in " ".join(reasons)


def test_acceptance_counts_drafts_across_fanout_output() -> None:
    met, reasons = evaluate_mission_acceptance(
        tasks=[
            _task(
                {
                    "introduction_drafts": [{"prospect_id": "p1"}, {"prospect_id": "p2"}],
                }
            )
        ],
        contract={"draft_min": 2},
    )

    assert met is True
    assert reasons == []


def test_acceptance_counts_verified_directory_resolutions() -> None:
    met, reasons = evaluate_mission_acceptance(
        tasks=[
            _task(
                {
                    "prospect_candidates": [],
                    "verified_prospect_candidates": [
                        {
                            "prospect_id": "web:acme",
                            "company": "Acme HVAC",
                            "identity_status": "verified",
                        }
                    ],
                }
            )
        ],
        contract={"candidate_min": 1, "require_verified_identity": True},
    )

    assert met is True
    assert reasons == []


def test_acceptance_requires_research_report_opportunities() -> None:
    task = _task({"research_report": {"comparison": [], "market_opportunities": [{"title": "one"}]}})
    met, reasons = evaluate_mission_acceptance(
        tasks=[task],
        contract={"research_report_required": True, "market_opportunities_min": 3},
    )

    assert met is False
    assert "market opportunities" in " ".join(reasons)

    complete = _task(
        {
            "research_report": {
                "comparison": [],
                "market_opportunities": [{"title": "one"}, {"title": "two"}, {"title": "three"}],
            }
        }
    )
    met, reasons = evaluate_mission_acceptance(
        tasks=[complete],
        contract={"research_report_required": True, "market_opportunities_min": 3},
    )
    assert met is True
    assert reasons == []


def test_acceptance_requires_business_review_opportunities() -> None:
    incomplete = _task({"business_review_report": {"income_opportunities": []}})
    met, reasons = evaluate_mission_acceptance(
        tasks=[incomplete],
        contract={"business_review_required": True, "business_opportunities_min": 3},
    )
    assert met is False
    assert "income opportunities" in " ".join(reasons)

    complete = _task(
        {"business_review_report": {"income_opportunities": [{"title": "one"}, {"title": "two"}, {"title": "three"}]}}
    )
    met, reasons = evaluate_mission_acceptance(
        tasks=[complete],
        contract={"business_review_required": True, "business_opportunities_min": 3},
    )
    assert met is True
    assert reasons == []


def test_acceptance_requires_internal_crm_readback_evidence() -> None:
    persisted_only = _task({"internal_crm_records": [{"id": "contact-1", "company": "Acme"}]})
    met, reasons = evaluate_mission_acceptance(
        tasks=[persisted_only],
        contract={"internal_crm_records_min": 1, "internal_crm_readback_required": True},
    )
    assert met is False
    assert "read-back evidence" in " ".join(reasons)

    verified = _task(
        {
            "internal_crm_records": [{"id": "contact-1", "company": "Acme"}],
            "crm_readback_records": [{"record_id": "contact-1", "verified": True}],
        }
    )
    met, reasons = evaluate_mission_acceptance(
        tasks=[verified],
        contract={"internal_crm_records_min": 1, "internal_crm_readback_required": True},
    )
    assert met is True
    assert reasons == []


def test_acceptance_requires_internal_crm_opportunity_projection() -> None:
    output = {
        "internal_crm_records": [{"id": "contact-1", "company": "Acme"}],
        "crm_readback_records": [{"record_id": "contact-1", "verified": True}],
        "crm_projection_records": [{"contact_id": "contact-1", "opportunity_id": "opp-1"}],
    }
    met, reasons = evaluate_mission_acceptance(
        tasks=[_task(output)],
        contract={
            "internal_crm_records_min": 1,
            "internal_crm_readback_required": True,
            "internal_crm_opportunities_min": 1,
        },
    )
    assert met is True
    assert reasons == []

    met, reasons = evaluate_mission_acceptance(
        tasks=[_task({**output, "crm_projection_records": []})],
        contract={
            "internal_crm_records_min": 1,
            "internal_crm_readback_required": True,
            "internal_crm_opportunities_min": 1,
        },
    )
    assert met is False
    assert "opportunity projection" in " ".join(reasons)

    unrelated_projection = _task(
        {
            "internal_crm_records": [{"id": "contact-1", "company": "Acme"}],
            "crm_readback_records": [{"record_id": "contact-1", "verified": True}],
            "crm_projection_records": [{"contact_id": "contact-2", "opportunity_id": "opp-2"}],
        }
    )
    met, reasons = evaluate_mission_acceptance(
        tasks=[unrelated_projection],
        contract={
            "internal_crm_records_min": 1,
            "internal_crm_readback_required": True,
            "internal_crm_opportunities_min": 1,
        },
    )
    assert met is False
    assert "opportunity projection" in " ".join(reasons)
