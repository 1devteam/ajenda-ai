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
