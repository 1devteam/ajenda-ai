from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.services.business_context_resolver import default_company_and_domain
from backend.services.knowledge.knowledge_applicability import SourceConditionObservation
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
    EvidenceSourceIdentity,
)
from backend.services.plugins.crm_client import default_crm_client, is_live_external_crm_result
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.record_store import RecordStore, record_store_limitations, resolve_record_store
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    FollowupDraftInput,
    RecordReadInput,
    RecordSearchInput,
    RecordWriteInput,
    RuntimeCredentialMaterial,
    SalesLeadInput,
    SideEffectClass,
    ToolInvocation,
)
from backend.services.tools.side_effect_resolvers import credential_reference_external_read


def _provider(context: ActionRuntimeContext) -> RecordStore:
    return resolve_record_store(context)


def _evidence(
    *,
    context: ActionRuntimeContext,
    action: str,
    provider: str,
    summary: str,
    payload: dict[str, Any],
    inspected: list[str] | None = None,
    changed: list[str] | None = None,
    side_effect_class: SideEffectClass = SideEffectClass.NONE,
    confidence: float | None = 1.0,
    source_observation: bool = False,
    source_identity: EvidenceSourceIdentity | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="action_result",
        evidence_source=f"tool.invoke.{action}",
        action_name=action,
        tool_provider=provider,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id is not None else None,
        summary=summary,
        structured_payload=payload,
        records_inspected=inspected or [],
        records_changed=changed or [],
        confidence=confidence,
        limitations=record_store_limitations(context),
        provenance={"runtime_path": "TaskDispatcher -> tool.invoke -> ActionRegistry"},
        lineage=(
            EvidenceLineage(
                artifact_evidence_id=f"action-result:{context.task_id}",
                origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
                source_identity=source_identity,
                resolution=(
                    EvidenceLineageResolution.KNOWN
                    if source_identity is not None
                    else EvidenceLineageResolution.UNKNOWN
                ),
            )
            if source_observation
            else None
        ),
        side_effect_class=side_effect_class,
    )


def record_search(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = RecordSearchInput.model_validate(invocation.input)
    records = _provider(context).search_records(
        tenant_id=context.tenant_id,
        record_type=payload.record_type,
        query=payload.query,
        filters=payload.filters,
        limit=payload.limit,
    )
    inspected = [str(record["id"]) for record in records if "id" in record]
    output = {"record_type": payload.record_type, "records": records, "count": len(records)}
    summary = f"Found {len(records)} {payload.record_type} record(s)."
    return ActionResult(
        action="record.search",
        provider="local_records",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="record.search",
                provider="local_records",
                summary=summary,
                payload=output,
                inspected=inspected,
                source_observation=True,
            )
        ],
        records_inspected=inspected,
        summary=summary,
        confidence=1.0,
    )


def record_read(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = RecordReadInput.model_validate(invocation.input)
    record = _provider(context).read_record(
        tenant_id=context.tenant_id,
        record_type=payload.record_type,
        record_id=payload.record_id,
    )
    raw_condition_observations = record.get("condition_observations", []) if record is not None else []
    if not isinstance(raw_condition_observations, list):
        raise ValueError("record condition_observations must be a list")
    condition_observations = tuple(
        SourceConditionObservation.model_validate(item) for item in raw_condition_observations
    )
    observation_keys = [
        (
            item.condition_key,
            tuple((subject.object_type.value, subject.object_id) for subject in item.subject_refs),
        )
        for item in condition_observations
    ]
    if len(observation_keys) != len(set(observation_keys)):
        raise ValueError("record condition_observations must be unique per condition and subject")
    output = {
        "record_type": payload.record_type,
        "record": record,
        "found": record is not None,
        "condition_observations": [item.model_dump(mode="json") for item in condition_observations],
    }
    summary = f"Read {payload.record_type} record {payload.record_id}: {'found' if record else 'not found'}."
    inspected = [payload.record_id] if record else []
    return ActionResult(
        action="record.read",
        provider="local_records",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="record.read",
                provider="local_records",
                summary=summary,
                payload=output,
                inspected=inspected,
                source_observation=True,
                source_identity=(
                    EvidenceSourceIdentity(
                        source_system="tenant_record_store",
                        source_record_id=f"{payload.record_type}:{payload.record_id}",
                    )
                    if record is not None
                    else None
                ),
            )
        ],
        records_inspected=inspected,
        summary=summary,
        confidence=1.0,
    )


def record_write(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = RecordWriteInput.model_validate(invocation.input)
    record = _provider(context).write_record(
        tenant_id=context.tenant_id,
        record_type=payload.record_type,
        record_id=payload.record_id,
        data=payload.data,
    )
    changed = [str(record["id"])]
    output = {
        "record_type": payload.record_type,
        "record": record,
        # Owner-authoritative event time: captured only after the write returns.
        "executed_at": datetime.now(UTC).isoformat(),
    }
    summary = f"Wrote {payload.record_type} record {record['id']} in local proof provider."
    return ActionResult(
        action="record.write",
        provider="local_records",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="record.write",
                provider="local_records",
                summary=summary,
                payload=output,
                changed=changed,
                side_effect_class=SideEffectClass.INTERNAL_WRITE,
            )
        ],
        records_changed=changed,
        summary=summary,
        confidence=1.0,
    )


def sales_research(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = SalesLeadInput.model_validate(invocation.input)
    account_id = payload.account_id or str(payload.lead.get("account_id", ""))
    related = []
    if account_id:
        account = _provider(context).read_record(
            tenant_id=context.tenant_id, record_type="account", record_id=account_id
        )
        if account:
            related.append(account)

    context_map = payload.context if isinstance(payload.context, dict) else {}
    require_external_crm = bool(context_map.get("require_external_crm"))

    cred: RuntimeCredentialMaterial | dict[str, Any] | None = context.runtime_credentials.get(
        "sales.research"
    ) or context.runtime_credentials.get("crm.research")
    company, domain = default_company_and_domain(
        context=context,
        company=str(payload.lead.get("company", "") or ""),
        domain=str(payload.lead.get("domain", "") or "") or None,
    )
    search = default_crm_client().search(
        context=context,
        company=company,
        domain=domain,
        credential=cred,
        invocation=invocation,
        action_name="sales.research",
    )

    use_external = is_live_external_crm_result(
        source=search.source,
        real=search.real,
        error=search.error,
    )
    provider = "ajenda_brain"
    attempted_external = invocation.credential_reference is not None or cred is not None
    side_effect_class = (
        SideEffectClass.EXTERNAL_READ if invocation.credential_reference is not None else SideEffectClass.INTERNAL_READ
    )
    external_attempt_failed = bool(attempted_external and search.error)

    # Explicit HubSpot / CRM-read missions must not silently complete on brain fallback.
    if require_external_crm:
        if search.error:
            raise ValueError(
                f"HubSpot CRM read failed and internal brain fallback is disabled for this mission: {search.error}"
            )
        if not use_external:
            raise ValueError(
                "HubSpot CRM read required external records but no live HubSpot result was returned; "
                "refusing Ajenda-brain fallback for explicit CRM read"
            )

    research_notes = (
        [f"external CRM plugin search via {search.source} (count={search.count})"]
        if use_external
        else [f"Ajenda central brain search (count={search.count})"]
    )
    if external_attempt_failed:
        research_notes.append(f"external attempt failed: {search.error}; used internal brain fallback")

    output = {
        "lead": payload.lead,
        "related_records": related,
        "crm_matches": search.results,
        "research_notes": research_notes,
        "real": True,
        "plugin_required": use_external,
        "source": search.source,
        "hybrid_mode": external_attempt_failed,
    }
    if external_attempt_failed:
        output["external_attempt_failed"] = True
    if use_external and cred is not None:
        output["credential_reference"] = {
            "provider": getattr(getattr(cred, "reference", None), "provider", None)
            if not isinstance(cred, dict)
            else cred.get("provider"),
        }
        if search.status_code is not None:
            output["real_response"] = {"status_code": search.status_code}
        if invocation.idempotency_key:
            output["idempotency_key"] = invocation.idempotency_key

    inspected = [str(item["id"]) for item in related if "id" in item]
    inspected.extend(str(item["id"]) for item in search.results if isinstance(item, dict) and item.get("id"))
    summary = f"Researched lead with {len(related)} related record(s) and {search.count} CRM match(es)." + (
        " via external plugin" if use_external else " via Ajenda brain"
    )
    return ActionResult(
        action="sales.research",
        provider=provider,
        side_effect_class=side_effect_class,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.research",
                provider=provider,
                summary=summary,
                payload=output,
                inspected=inspected,
                side_effect_class=side_effect_class,
                confidence=0.9 if use_external else 0.85,
            )
        ],
        records_inspected=inspected,
        summary=summary,
        confidence=0.9 if use_external else 0.85,
    )


def _normalize_observed_lead(lead: dict[str, Any]) -> dict[str, Any]:
    """Map observe-contact records onto lead email/phone fields."""

    normalized = dict(lead)
    kind = str(normalized.get("kind") or "").strip().lower()
    value = str(normalized.get("value") or "").strip()
    if kind == "email" and value and not normalized.get("email"):
        normalized["email"] = value
    if kind == "phone" and value and not normalized.get("phone"):
        normalized["phone"] = value
    return normalized


def _is_invented_enrich_contact(lead: dict[str, Any]) -> bool:
    if lead.get("simulated") is True or lead.get("enrichment_mode") == "local_simulated":
        return True
    if str(lead.get("source") or "") == "local_gtm_heuristic":
        return True
    contacts = lead.get("contacts")
    if isinstance(contacts, list):
        for item in contacts:
            if not isinstance(item, dict):
                continue
            if item.get("simulated") is True or str(item.get("source") or "") == "local_gtm_heuristic":
                return True
    return False


def _has_real_contact(lead: dict[str, Any]) -> bool:
    """True only for a caller-supplied or observed mailbox/phone — not search snippets."""

    if _is_invented_enrich_contact(lead):
        return False
    email = str(lead.get("email") or "").strip()
    if email and "@" in email:
        local = email.split("@", 1)[0].lower()
        if local != "contact":
            return True
        if str(lead.get("source") or "") == "local_gtm_heuristic":
            return False
        return True
    if str(lead.get("phone") or "").strip():
        return True
    contacts = lead.get("contacts")
    if isinstance(contacts, list):
        for item in contacts:
            if not isinstance(item, dict):
                continue
            if item.get("real") is True and item.get("simulated") is not True:
                return True
            value = str(item.get("email") or item.get("value") or "").strip()
            if value and "@" in value and item.get("simulated") is not True:
                return True
    return False


def _first_lead_text(*values: Any) -> str:
    """Return explicit lead text without synthesizing missing facts."""

    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            items = [str(item).strip() for item in value if isinstance(item, str) and item.strip()]
            if items:
                return "; ".join(items)
    return ""


def _lead_source_references(lead: dict[str, Any]) -> list[str]:
    """Preserve explicit source references used by qualification."""

    references: list[str] = []
    raw_sources = lead.get("sources")
    values: list[Any] = list(raw_sources) if isinstance(raw_sources, (list, tuple)) else []
    raw_identity_sources = lead.get("identity_evidence_urls")
    if isinstance(raw_identity_sources, (list, tuple)):
        values.extend(raw_identity_sources)
    values.extend((lead.get("source_url"), lead.get("website"), lead.get("url")))
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if normalized and normalized not in references:
            references.append(normalized[:500])
    return references


def _ajenda_relevance(*, lead: dict[str, Any], context: dict[str, Any]) -> str:
    """Describe relevance only when the inputs contain an automation or intent signal."""

    opportunity = _first_lead_text(
        lead.get("automation_opportunity"),
        lead.get("workflow"),
        context.get("automation_opportunity"),
    )
    if opportunity:
        return f"Ajenda may be relevant to the observed automation opportunity: {opportunity[:500]}."
    intent = _first_lead_text(lead.get("intent"), context.get("intent"))
    if intent:
        return f"Ajenda may be relevant because the observed intent signal identifies a workflow to evaluate: {intent[:500]}."
    return ""

def _qualify_one(lead: dict[str, Any], *, context: dict[str, Any], account_id: str | None) -> dict[str, Any]:
    lead = _normalize_observed_lead(lead)
    fit_points = 0
    reasons: list[str] = []
    if lead.get("company") or account_id:
        fit_points += 35
        reasons.append("company/account context present")
    if lead.get("role") or lead.get("title"):
        fit_points += 25
        reasons.append("buyer role context present")
    if lead.get("intent") or context.get("intent"):
        fit_points += 25
        reasons.append("intent signal present")
    if _has_real_contact(lead):
        fit_points += 15
        reasons.append("contactability present")
    if lead.get("domain") or lead.get("url") or lead.get("signals"):
        fit_points += 15
        reasons.append("research signals present")
    if lead.get("source") == "public_search" or lead.get("source") == "internal_record":
        fit_points += 10
        reasons.append("sourced from research world-state")
    score = min(fit_points, 100)
    dimensions = {
        "business_fit": 10
        if (lead.get("company") or account_id) and (lead.get("industry") or lead.get("location") or account_id)
        else 5
        if (lead.get("company") or account_id)
        else 0,
        "automation_opportunity": 10
        if lead.get("automation_opportunity") or lead.get("workflow") or context.get("automation_opportunity")
        else 5
        if lead.get("intent") or context.get("intent")
        else 0,
        "evidence_quality": 10
        if lead.get("identity_status") == "verified" and (lead.get("source_url") or lead.get("url"))
        else 8
        if lead.get("source") == "internal_record"
        else 4
        if lead.get("signals") or lead.get("source_url") or lead.get("url")
        else 0,
        "urgency": 10 if lead.get("urgency") else 5 if lead.get("intent") or context.get("intent") else 0,
    }
    score_10 = round(sum(dimensions.values()) / len(dimensions))
    mission_scoring = bool(context.get("mission_specific_scoring")) or "qualification_threshold_10" in context
    threshold_10 = int(context.get("qualification_threshold_10", 7) or 7)
    qualified = _has_real_contact(lead) and (
        not mission_scoring or (score_10 >= threshold_10 and lead.get("identity_status") != "unverified")
    )
    if not qualified:
        reasons.append("not qualified without an observed or supplied contact")
    if lead.get("identity_status") == "unverified":
        reasons.append("identity is unverified")
    return {
        "score": score,
        "score_10": score_10,
        "qualification_dimensions": dimensions,
        "qualification_threshold_10": threshold_10,
        "qualified": qualified,
        "reasons": reasons or ["insufficient local qualification signals"],
    }


def sales_qualify(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = SalesLeadInput.model_validate(invocation.input)
    prospects_in = [p for p in payload.prospects if isinstance(p, dict)]
    if not prospects_in and (payload.lead or payload.account_id):
        prospects_in = [dict(payload.lead)] if payload.lead else [{"account_id": payload.account_id}]

    qualified_prospects: list[dict[str, Any]] = []
    scored_prospects: list[dict[str, Any]] = []
    for index, prospect in enumerate(prospects_in):
        lead = _normalize_observed_lead(dict(prospect))
        if payload.lead and index == 0:
            # Merge seed lead fields without overwriting bound prospect identity.
            for key, value in payload.lead.items():
                lead.setdefault(key, value)
        result = _qualify_one(lead, context=payload.context, account_id=payload.account_id)
        company = str(lead.get("company") or lead.get("name") or f"prospect-{index + 1}")[:160]
        sources = _lead_source_references(lead)
        website = _first_lead_text(lead.get("website"), lead.get("url"))
        if not website and lead.get("domain"):
            website = f"https://{str(lead['domain']).strip()}"
        product_description = _first_lead_text(
            lead.get("product_description"),
            lead.get("description"),
            lead.get("products_services"),
        )[:1000]
        research_summary = _first_lead_text(
            lead.get("research_summary"),
            lead.get("signals"),
            lead.get("research_notes"),
        )[:1000]
        qualification_evidence = {
            "qualification_dimensions": result["qualification_dimensions"],
            "qualification_reasons": result["reasons"],
            "source_references": sources,
        }
        entry = {
            **{k: v for k, v in lead.items() if k not in {"score", "qualified", "reasons"}},
            "prospect_id": str(lead.get("prospect_id") or lead.get("id") or f"qualify:{index}:{company}")[:80],
            "company": company,
            "website": website[:500],
            "product_description": product_description,
            "research_summary": research_summary,
            "sources": sources,
            "qualification_evidence": qualification_evidence,
            "ajenda_relevance": _ajenda_relevance(lead=lead, context=payload.context),
            "score": result["score"],
            "score_10": result["score_10"],
            "qualification_dimensions": result["qualification_dimensions"],
            "qualification_threshold_10": result["qualification_threshold_10"],
            "qualified": result["qualified"],
            "reasons": result["reasons"],
        }
        scored_prospects.append(entry)
        if result["qualified"]:
            qualified_prospects.append(entry)

    primary = (
        qualified_prospects[0]
        if qualified_prospects
        else scored_prospects[0]
        if scored_prospects
        else _qualify_one(payload.lead, context=payload.context, account_id=payload.account_id)
    )
    score = int(primary.get("score") or 0)
    qualified = bool(primary.get("qualified"))
    output = {
        "score": score,
        "score_10": primary.get("score_10", 0),
        "qualification_dimensions": primary.get("qualification_dimensions", {}),
        "qualification_threshold_10": primary.get("qualification_threshold_10", 7),
        "qualified": qualified,
        "reasons": primary.get("reasons") or ["insufficient local qualification signals"],
        "qualified_prospects": qualified_prospects,
        "prospect_count": len(qualified_prospects),
    }
    summary = f"Qualified {len(qualified_prospects)} prospect(s); primary score={score}, qualified={qualified}."
    return ActionResult(
        action="sales.qualify",
        provider="local_sales",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.qualify",
                provider="local_sales",
                summary=summary,
                payload=output,
                confidence=0.72,
            )
        ],
        summary=summary,
        confidence=0.72,
    )


def sales_score_lead(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    result = sales_qualify(invocation, context)
    output = {
        "lead_score": result.output["score"],
        "score_band": "high" if result.output["score"] >= 75 else "medium" if result.output["score"] >= 50 else "low",
        "reasons": result.output["reasons"],
    }
    summary = f"Lead score is {output['lead_score']} ({output['score_band']})."
    return ActionResult(
        action="sales.score_lead",
        provider="local_sales",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.score_lead",
                provider="local_sales",
                summary=summary,
                payload=output,
                confidence=0.72,
            )
        ],
        summary=summary,
        confidence=0.72,
    )


def sales_recommend_next_action(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = SalesLeadInput.model_validate(invocation.input)
    qualify_result = sales_qualify(invocation, context)
    score = int(qualify_result.output["score"])
    recommendation = "draft_followup" if score >= 60 else "research_more"
    rationale = (
        "Qualification score is high enough for follow-up."
        if score >= 60
        else "More account/contact context is needed."
    )
    output = {"recommendation": recommendation, "rationale": rationale, "lead": payload.lead, "score": score}
    summary = f"Recommended next action: {recommendation}."
    return ActionResult(
        action="sales.recommend_next_action",
        provider="local_sales",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.recommend_next_action",
                provider="local_sales",
                summary=summary,
                payload=output,
                confidence=0.7,
            )
        ],
        summary=summary,
        confidence=0.7,
    )


def sales_draft_followup(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = FollowupDraftInput.model_validate(invocation.input)
    from backend.services.draft_generation import generate_and_persist_draft

    output = generate_and_persist_draft(
        context,
        artifact_type="follow_up",
        topic=payload.topic,
        tone=payload.tone,
        recipient_name=payload.recipient_name,
        extra_context=payload.context,
    )
    mode = output.get("generation_mode", "template")
    summary = f"Drafted follow-up message ({mode}) without sending it."
    return ActionResult(
        action="sales.draft_followup",
        provider="local_sales",
        side_effect_class=SideEffectClass.NONE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.draft_followup",
                provider="local_sales",
                summary=summary,
                payload=output,
                confidence=0.8 if mode == "llm" else 0.74,
            )
        ],
        summary=summary,
        confidence=0.8 if mode == "llm" else 0.74,
    )


def sales_log_activity(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = RecordWriteInput.model_validate(invocation.input)
    write_invocation = ToolInvocation(
        action="record.write",
        input={
            "record_type": "activity",
            "record_id": payload.record_id,
            "data": payload.data,
        },
    )
    result = record_write(write_invocation, context)
    return ActionResult(
        action="sales.log_activity",
        provider="local_sales",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=result.output,
        evidence=[
            _evidence(
                context=context,
                action="sales.log_activity",
                provider="local_sales",
                summary="Logged local sales activity.",
                payload=result.output,
                changed=result.records_changed,
                side_effect_class=SideEffectClass.INTERNAL_WRITE,
            )
        ],
        records_changed=result.records_changed,
        summary="Logged local sales activity.",
        confidence=1.0,
    )


def sales_create_followup_task(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = RecordWriteInput.model_validate(invocation.input)
    write_invocation = ToolInvocation(
        action="record.write",
        input={
            "record_type": "task",
            "record_id": payload.record_id,
            "data": payload.data,
        },
    )
    result = record_write(write_invocation, context)
    return ActionResult(
        action="sales.create_followup_task",
        provider="local_sales",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=result.output,
        evidence=[
            _evidence(
                context=context,
                action="sales.create_followup_task",
                provider="local_sales",
                summary="Created local follow-up task.",
                payload=result.output,
                changed=result.records_changed,
                side_effect_class=SideEffectClass.INTERNAL_WRITE,
            )
        ],
        records_changed=result.records_changed,
        summary="Created local follow-up task.",
        confidence=1.0,
    )


def register_sales_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="record.search", handler=record_search, provider="local_records", input_model=RecordSearchInput
        )
    )
    registry.register(
        ActionDefinition(name="record.read", handler=record_read, provider="local_records", input_model=RecordReadInput)
    )
    registry.register(
        ActionDefinition(
            name="record.write",
            handler=record_write,
            provider="local_records",
            input_model=RecordWriteInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.research",
            handler=sales_research,
            provider="ajenda_brain",
            input_model=SalesLeadInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
            side_effect_resolver=credential_reference_external_read,
            aliases=("crm.research", "crm.read"),
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.qualify", handler=sales_qualify, provider="local_sales", input_model=SalesLeadInput
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.score_lead", handler=sales_score_lead, provider="local_sales", input_model=SalesLeadInput
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.recommend_next_action",
            handler=sales_recommend_next_action,
            provider="local_sales",
            input_model=SalesLeadInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.draft_followup",
            handler=sales_draft_followup,
            provider="local_sales",
            input_model=FollowupDraftInput,
            aliases=("gtm.message_draft",),
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.log_activity",
            handler=sales_log_activity,
            provider="local_sales",
            input_model=RecordWriteInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.create_followup_task",
            handler=sales_create_followup_task,
            provider="local_sales",
            input_model=RecordWriteInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
