"""Evidence Intelligence — decision support abilities (Slice 1 + commercial context).

Real abilities, not a StrategyEngine. This module implements
``decision.recommend_next_action``: given a goal, options, criteria, and
evidence facts, produce a defensible next-action recommendation with
supporting evidence, confidence, uncertainty, and change conditions.

Optional Commercial State Slice 2 fields (subject_refs, goal_ref, kpis,
state_snapshot, recent_events) are accepted and echoed for structured framing;
they do not alter weighted_criterion_evidence_v1 scoring.

Does not execute the recommendation, enqueue work, or wire composition.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
)
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    DecisionRecommendInput,
    EvidenceFact,
    EvidenceFactStatus,
    EvidenceItem,
    SideEffectClass,
    ToolInvocation,
)


def _evidence(
    *,
    context: ActionRuntimeContext,
    action: str,
    provider: str,
    summary: str,
    payload: dict[str, Any],
    confidence: float | None,
) -> EvidenceItem:
    supporting_ids = payload.get("supporting_evidence_ids", [])
    parent_ids = tuple(item for item in supporting_ids if isinstance(item, str) and item.strip())
    return EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="decision_actions",
        action_name=action,
        tool_provider=provider,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id is not None else None,
        summary=summary,
        structured_payload=payload,
        confidence=confidence,
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> ActionRegistry",
            "cluster": "evidence_intelligence",
            "evidence_role": "decision_recommendation_result",
        },
        lineage=EvidenceLineage(
            artifact_evidence_id=f"decision-result:{context.task_id}",
            origin_type=EvidenceOriginType.SYSTEM_COMPUTATION,
            parent_evidence_ids=parent_ids,
            resolution=(EvidenceLineageResolution.PARTIAL if parent_ids else EvidenceLineageResolution.UNKNOWN),
        ),
        side_effect_class=SideEffectClass.NONE,
    )


def _normalize_facts(raw: list[EvidenceFact]) -> list[EvidenceFact]:
    return list(raw)


def _commercial_context(payload: DecisionRecommendInput) -> dict[str, Any] | None:
    """Serialize optional Slice 2 commercial framing when any field is present."""

    has_any = (
        bool(payload.subject_refs)
        or payload.goal_ref is not None
        or bool(payload.kpis)
        or payload.state_snapshot is not None
        or bool(payload.recent_events)
    )
    if not has_any:
        return None
    return {
        "subject_refs": [ref.model_dump(mode="json") for ref in payload.subject_refs],
        "goal_ref": payload.goal_ref.model_dump(mode="json") if payload.goal_ref else None,
        "kpis": [kpi.model_dump(mode="json") for kpi in payload.kpis],
        "state_snapshot": (payload.state_snapshot.model_dump(mode="json") if payload.state_snapshot else None),
        "recent_events": [evt.model_dump(mode="json") for evt in payload.recent_events],
    }


def _score_option(
    *,
    option_id: str,
    criteria: list[Any],
    facts: list[EvidenceFact],
) -> dict[str, Any]:
    """Score one option against criteria using explicit evidence linkage.

    Algorithms forced into the open:
    - criterion weight defaults to equal share when unspecified
    - known evidence contributes full weight * fact.confidence
    - inferred evidence contributes 0.6 * weight * fact.confidence
    - missing evidence on a required criterion zeros that criterion and flags gap
    - unsupported criteria (no linked fact) count as missing for that option
    """
    if not criteria:
        return {
            "option_id": option_id,
            "total_score": 0.0,
            "dimension_scores": [],
            "supporting_evidence_ids": [],
            "missing_criterion_ids": [],
            "gaps": ["no_criteria_supplied"],
        }

    total_weight = sum(float(c.weight) for c in criteria) or float(len(criteria))
    dimension_scores: list[dict[str, Any]] = []
    supporting: list[str] = []
    missing: list[str] = []
    gaps: list[str] = []
    weighted_sum = 0.0

    for criterion in criteria:
        cid = criterion.criterion_id
        weight = float(criterion.weight) / total_weight
        linked = [
            f
            for f in facts
            if cid in f.supports_criterion_ids and (not f.supports_option_ids or option_id in f.supports_option_ids)
        ]
        if not linked:
            dim_score = 0.0
            status = "unsupported"
            missing.append(cid)
            if criterion.required:
                gaps.append(f"required_criterion_unsupported:{cid}")
            reason = "no evidence linked to this criterion for this option"
            fact_ids: list[str] = []
        else:
            # Prefer strongest contribution among linked facts
            contribs: list[tuple[float, EvidenceFact]] = []
            for fact in linked:
                if fact.status == EvidenceFactStatus.KNOWN:
                    contribs.append((1.0 * float(fact.confidence), fact))
                elif fact.status == EvidenceFactStatus.INFERRED:
                    contribs.append((0.6 * float(fact.confidence), fact))
                else:  # missing
                    contribs.append((0.0, fact))
                    missing.append(cid)
                    if criterion.required:
                        gaps.append(f"required_evidence_missing:{cid}:{fact.evidence_id}")
            contribs.sort(key=lambda item: item[0], reverse=True)
            dim_score, best = contribs[0]
            status = best.status.value
            reason = best.claim
            fact_ids = [f.evidence_id for f in linked]
            supporting.extend(fact_ids)

        dimension_scores.append(
            {
                "criterion_id": cid,
                "label": criterion.label,
                "weight": round(weight, 4),
                "score": round(dim_score, 4),
                "status": status,
                "reason": reason,
                "evidence_ids": fact_ids,
            }
        )
        weighted_sum += dim_score * weight

    # Deduplicate supporting ids while preserving order
    seen: set[str] = set()
    unique_supporting: list[str] = []
    for eid in supporting:
        if eid not in seen:
            seen.add(eid)
            unique_supporting.append(eid)

    return {
        "option_id": option_id,
        "total_score": round(weighted_sum, 4),
        "dimension_scores": dimension_scores,
        "supporting_evidence_ids": unique_supporting,
        "missing_criterion_ids": sorted(set(missing)),
        "gaps": gaps,
    }


def _feasibility(option_id: str, constraints: list[str], facts: list[EvidenceFact]) -> dict[str, Any]:
    """Lightweight feasibility: constraints that mention the option and conflict with known facts."""
    blocking: list[str] = []
    for constraint in constraints:
        text = constraint.strip().lower()
        if not text:
            continue
        # Explicit hard-block pattern: "must not <option_id>" or "forbid:<option_id>"
        if f"forbid:{option_id.lower()}" in text or f"must not {option_id.lower()}" in text:
            blocking.append(constraint)
        # Fact-declared infeasibility
        for fact in facts:
            if (
                fact.status == EvidenceFactStatus.KNOWN
                and option_id in fact.supports_option_ids
                and "infeasible" in fact.claim.lower()
            ):
                blocking.append(f"evidence:{fact.evidence_id}:{fact.claim}")
    return {"feasible": len(blocking) == 0, "blocking_constraints": blocking}


def decision_recommend_next_action(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    decided_at = datetime.now(UTC)
    payload = DecisionRecommendInput.model_validate(invocation.input)
    facts = _normalize_facts(list(payload.evidence))
    criteria = list(payload.criteria)
    options = list(payload.options)
    constraints = list(payload.constraints)

    if not payload.goal.strip():
        raise ValueError("goal must be non-empty")

    scored: list[dict[str, Any]] = []
    for option in options:
        score_row = _score_option(option_id=option.option_id, criteria=criteria, facts=facts)
        feas = _feasibility(option.option_id, constraints, facts)
        score_row["label"] = option.label
        score_row["description"] = option.description
        score_row["intervention_key"] = option.intervention_key
        score_row["feasible"] = feas["feasible"]
        score_row["blocking_constraints"] = feas["blocking_constraints"]
        # Confidence: mean of linked known/inferred fact confidences, penalize gaps
        linked_conf = [
            float(f.confidence)
            for f in facts
            if f.evidence_id in score_row["supporting_evidence_ids"] and f.status != EvidenceFactStatus.MISSING
        ]
        base_conf = sum(linked_conf) / len(linked_conf) if linked_conf else 0.35
        gap_penalty = min(0.4, 0.08 * len(score_row["gaps"]))
        score_row["confidence"] = round(max(0.05, base_conf - gap_penalty), 4)
        if not feas["feasible"]:
            score_row["total_score"] = 0.0
            score_row["confidence"] = round(min(score_row["confidence"], 0.2), 4)
        scored.append(score_row)

    scored.sort(key=lambda row: (row["feasible"], row["total_score"], row["confidence"]), reverse=True)

    if not options:
        recommendation = "gather_more_evidence"
        rationale = "No candidate options were supplied; collect evidence and define options before deciding."
        chosen = None
        confidence = 0.4
        supporting: list[str] = [f.evidence_id for f in facts if f.status != EvidenceFactStatus.MISSING][:10]
        what_would_change = [
            "Provide at least one candidate option with option_id and label.",
            "Attach evidence facts linked to criteria and options.",
        ]
        uncertainty = ["options_absent", "decision_space_undefined"]
    else:
        chosen = scored[0]
        if not chosen["feasible"] or chosen["total_score"] <= 0:
            recommendation = "gather_more_evidence"
            rationale = (
                f"No feasible scored option cleared the bar. "
                f"Top candidate '{chosen['label']}' score={chosen['total_score']} "
                f"gaps={chosen['gaps'] or chosen['blocking_constraints']}."
            )
            confidence = min(0.45, float(chosen["confidence"]))
            supporting = list(chosen["supporting_evidence_ids"])
            what_would_change = [
                "Resolve required criterion gaps with known evidence.",
                "Remove or satisfy blocking constraints.",
                "Add alternative options if the current set is infeasible.",
            ]
            uncertainty = ["no_feasible_option", *list(chosen["gaps"])[:5]]
        else:
            recommendation = chosen["option_id"]
            rationale = (
                f"Recommend '{chosen['label']}' for goal '{payload.goal}' "
                f"with score={chosen['total_score']} confidence={chosen['confidence']}."
            )
            if chosen["dimension_scores"]:
                top_dims = sorted(chosen["dimension_scores"], key=lambda d: d["score"], reverse=True)[:3]
                dim_bits = ", ".join(f"{d['label']}={d['score']}" for d in top_dims)
                rationale = f"{rationale} Leading dimensions: {dim_bits}."
            confidence = float(chosen["confidence"])
            supporting = list(chosen["supporting_evidence_ids"])
            what_would_change = []
            for gap in chosen["gaps"][:5]:
                what_would_change.append(f"Resolve gap: {gap}")
            if len(scored) > 1 and scored[1]["feasible"]:
                delta = round(chosen["total_score"] - scored[1]["total_score"], 4)
                what_would_change.append(
                    f"Evidence that raises '{scored[1]['label']}' by more than {delta} could change the ranking."
                )
            if not what_would_change:
                what_would_change.append(
                    "Contradictory known evidence against the leading dimensions could reverse this recommendation."
                )
            uncertainty = []
            if any(d["status"] == "inferred" for d in chosen["dimension_scores"]):
                uncertainty.append("relies_on_inferred_evidence")
            if chosen["missing_criterion_ids"]:
                uncertainty.append("partial_criterion_coverage")
            if confidence < 0.6:
                uncertainty.append("low_confidence")

    output: dict[str, Any] = {
        "decided_at": decided_at.isoformat(),
        "goal": payload.goal,
        "recommendation": recommendation,
        "intervention_key": chosen.get("intervention_key")
        if chosen is not None and recommendation == chosen["option_id"]
        else None,
        "rationale": rationale,
        "confidence": confidence,
        "uncertainty": uncertainty,
        "supporting_evidence_ids": supporting,
        "what_would_change_recommendation": what_would_change,
        "option_scores": scored,
        "algorithm": {
            "name": "weighted_criterion_evidence_v1",
            "version": "1",
            "known_weight": 1.0,
            "inferred_weight": 0.6,
            "missing_weight": 0.0,
            "notes": (
                "Deterministic scoring from explicit evidence linkage. "
                "Does not execute the recommendation. Commercial context is "
                "echoed when supplied but does not alter v1 scores."
            ),
        },
    }
    commercial = _commercial_context(payload)
    if commercial is not None:
        output["commercial_context"] = commercial

    summary = f"Recommended next action: {recommendation} (confidence={confidence})."
    return ActionResult(
        action="decision.recommend_next_action",
        provider="ajenda_decision",
        side_effect_class=SideEffectClass.NONE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="decision.recommend_next_action",
                provider="ajenda_decision",
                summary=summary,
                payload=output,
                confidence=confidence,
            )
        ],
        summary=summary,
        confidence=confidence,
    )


def register_decision_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="decision.recommend_next_action",
            handler=decision_recommend_next_action,
            provider="ajenda_decision",
            input_model=DecisionRecommendInput,
            side_effect_class=SideEffectClass.NONE,
        )
    )
