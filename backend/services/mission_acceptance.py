"""Evaluate outcome-level acceptance from durable task outputs."""

from __future__ import annotations

from typing import Any


def evaluate_mission_acceptance(*, tasks: list[Any], contract: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return whether a composition mission produced its required deliverables."""

    if not contract:
        return True, []

    outputs: list[dict[str, Any]] = []
    for task in tasks:
        metadata = task.metadata_json if isinstance(getattr(task, "metadata_json", None), dict) else {}
        result = metadata.get("handler_result")
        if not isinstance(result, dict):
            continue
        nested = result.get("output")
        outputs.append(nested if isinstance(nested, dict) else result)

    reasons: list[str] = []

    def unique_records(key: str) -> list[dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for output in outputs:
            for item in output.get(key, []):
                if not isinstance(item, dict):
                    continue
                identity = str(
                    item.get("prospect_id")
                    or item.get("company")
                    or item.get("domain")
                    or item.get("artifact_id")
                    or len(records)
                )
                records[identity] = item
        return list(records.values())

    candidates = unique_records("prospect_candidates")
    qualified = unique_records("qualified_prospects")
    drafts = unique_records("introduction_drafts")

    candidate_min = int(contract.get("candidate_min", 0) or 0)
    if len(candidates) < candidate_min:
        reasons.append(f"required at least {candidate_min} prospect candidates, produced {len(candidates)}")

    if contract.get("require_verified_identity"):
        verified = [item for item in candidates if item.get("identity_status") == "verified"]
        if len(verified) < candidate_min:
            reasons.append(f"required {candidate_min} verified prospect identities, produced {len(verified)}")

    qualified_min = int(contract.get("qualified_min", 0) or 0)
    threshold = int(contract.get("score_threshold_10", 7) or 7)
    thresholded = [item for item in qualified if int(item.get("score_10", 0) or 0) >= threshold]
    if len(thresholded) < qualified_min:
        reasons.append(
            f"required at least {qualified_min} qualified prospects scoring {threshold}/10, produced {len(thresholded)}"
        )

    draft_min = int(contract.get("draft_min", 0) or 0)
    if len(drafts) < draft_min:
        reasons.append(f"required at least {draft_min} outreach drafts, produced {len(drafts)}")

    return not reasons, reasons
