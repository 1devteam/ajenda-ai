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
    # Public identity observation may promote directory links after the
    # discovery task has completed. Those verified identities are emitted by
    # the observation task and count toward the same candidate contract.
    observed_candidates = unique_records("verified_prospect_candidates")
    for item in observed_candidates:
        identity = str(item.get("prospect_id") or item.get("company") or item.get("domain") or "")
        if identity and not any(
            str(existing.get("prospect_id") or existing.get("company") or existing.get("domain") or "") == identity
            for existing in candidates
        ):
            candidates.append(item)
    qualified = unique_records("qualified_prospects")
    drafts = unique_records("introduction_drafts")

    reports: list[dict[str, Any]] = []
    for output in outputs:
        report = output.get("research_report")
        if isinstance(report, dict):
            reports.append(report)

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

    report_required = bool(contract.get("research_report_required", False))
    opportunity_min = int(contract.get("market_opportunities_min", 0) or 0)
    if report_required and not reports:
        reasons.append("required a research_report artifact, produced 0")
    if opportunity_min:
        opportunities = [
            item
            for report in reports
            for item in report.get("market_opportunities", [])
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ]
        if len(opportunities) < opportunity_min:
            reasons.append(
                f"required at least {opportunity_min} market opportunities in research_report, produced {len(opportunities)}"
            )

    crm_records = unique_records("internal_crm_records")
    crm_min = int(contract.get("internal_crm_records_min", 0) or 0)
    if len(crm_records) < crm_min:
        reasons.append(f"required at least {crm_min} persisted internal CRM records, produced {len(crm_records)}")
    if contract.get("internal_crm_readback_required"):
        verified_ids = {
            str(item.get("record_id"))
            for output in outputs
            for item in output.get("crm_readback_records", [])
            if isinstance(item, dict) and item.get("verified") is True and item.get("record_id")
        }
        persisted_ids = {str(item.get("id")) for item in crm_records if item.get("id")}
        missing_readback = sorted(persisted_ids - verified_ids)
        if not persisted_ids or missing_readback:
            reasons.append(
                "required verified internal CRM read-back evidence for every persisted record; "
                f"missing {len(missing_readback) if persisted_ids else crm_min}"
            )

    opportunity_min = int(contract.get("internal_crm_opportunities_min", 0) or 0)
    if opportunity_min:
        persisted_contact_ids = {str(item.get("id")) for item in crm_records if item.get("id")}
        projections = [
            item for output in outputs for item in output.get("crm_projection_records", []) if isinstance(item, dict)
        ]
        projected_opportunities = {
            str(item.get("contact_id"))
            for item in projections
            if item.get("contact_id") in persisted_contact_ids and item.get("opportunity_id")
        }
        if len(projected_opportunities) < opportunity_min:
            reasons.append(
                "required an internal CRM opportunity projection for every persisted record; "
                f"produced {len(projected_opportunities)} of {opportunity_min}"
            )

    return not reasons, reasons
