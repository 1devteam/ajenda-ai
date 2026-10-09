"""Tenant-scoped record search/read/write actions."""

from __future__ import annotations

import hashlib

import json

from datetime import (
    UTC,
    datetime,
)

from typing import Any

from backend.db.tenant_session import activate_tenant_session

from backend.services.knowledge.knowledge_applicability import SourceConditionObservation

from backend.services.light_crm.records import LightCrmRecordService

from backend.services.light_crm.workflow import complete_internal_crm_upsert

from backend.services.ontology.evidence_lineage import EvidenceSourceIdentity

from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    RecordReadInput,
    RecordSearchInput,
    RecordWriteInput,
    SideEffectClass,
    ToolInvocation,
)

from backend.services.tools.sales_action_common import _evidence, _provider

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
    # Preserve raw rows for auditability and expose a normalized alias for
    # composed qualification/drafting. Tenant-scoped internal rows are already
    # identity-bearing; they must not be treated like unverified public hits.
    crm_records: list[dict[str, Any]] = []
    for record in records:
        normalized = dict(record)
        normalized.setdefault("prospect_id", str(record.get("id") or ""))
        normalized.setdefault("company", record.get("name") or record.get("title"))
        normalized.setdefault("source", "internal_record")
        normalized.setdefault("identity_status", "verified")
        if payload.record_type == "account":
            # Bind observation to tenant-owned CRM relationships rather than
            # inventing contact data or falling back to public discovery.
            related_contacts = _provider(context).search_records(
                tenant_id=context.tenant_id,
                record_type="contact",
                filters={"account_id": str(record.get("id") or "")},
                limit=50,
            )
            if related_contacts:
                normalized["contacts"] = related_contacts
        crm_records.append(normalized)
    output = {
        "record_type": payload.record_type,
        "records": records,
        # Canonical mission artifact alias for the internal CRM → GTM path.
        # Keep ``records`` for existing callers and evidence consumers.
        "crm_records": crm_records,
        "count": len(crm_records),
    }
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
    if payload.tenant_id is not None and payload.tenant_id != context.tenant_id:
        raise ValueError("record.write tenant_id must match the runtime tenant")

    composition_context = payload.context.get("source") == "mission_composition"
    if composition_context:
        enriched = [dict(item) for item in payload.context.get("enriched_prospects", []) if isinstance(item, dict)]
        prospects = enriched or [
            dict(item) for item in payload.context.get("qualified_prospects", []) if isinstance(item, dict)
        ]
        if not prospects:
            raise ValueError("record.write requires at least one qualified prospect")
    else:
        prospects = [dict(item) for item in payload.context.get("prospect_candidates", []) if isinstance(item, dict)]
    observed_contacts = [dict(item) for item in payload.context.get("observed_contacts", []) if isinstance(item, dict)]
    if prospects:
        persisted: list[dict[str, Any]] = []
        readback: list[dict[str, Any]] = []
        projections: list[dict[str, Any]] = []
        session = context.session_factory() if callable(context.session_factory) else None
        provider = None if session is not None else _provider(context)
        try:
            if session is not None:
                activate_tenant_session(session, context.tenant_id)
            for prospect in prospects:
                identity = str(
                    prospect.get("prospect_id")
                    or prospect.get("domain")
                    or prospect.get("company")
                    or prospect.get("name")
                    or ""
                ).strip()
                if not identity:
                    raise ValueError("record.write internal CRM prospect requires a stable identity")
                canonical_identity = identity.casefold()
                record_id = f"contact-ajenda-{hashlib.sha256(canonical_identity.encode()).hexdigest()[:20]}"
                matching_contacts = [
                    item
                    for item in observed_contacts
                    if canonical_identity
                    in {
                        str(item.get("prospect_id") or "").strip().casefold(),
                        str(item.get("domain") or "").strip().casefold(),
                        str(item.get("company") or item.get("name") or "").strip().casefold(),
                    }
                ]
                record_data = {
                    **prospect,
                    "id": record_id,
                    "source": "mission_composition",
                    "workflow_context": str(payload.context.get("workflow_context") or "crm"),
                    "canonical_identity": canonical_identity,
                    "lifecycle_stage": "observed",
                    "observed_contacts": matching_contacts,
                }
                store = LightCrmRecordService(session=session) if session is not None else None
                read_store = store if store is not None else provider
                assert read_store is not None
                existing = read_store.read_record(
                    tenant_id=context.tenant_id, record_type=payload.record_type, record_id=record_id
                )
                if session is not None:
                    written = complete_internal_crm_upsert(
                        session=session,
                        tenant_id=context.tenant_id,
                        record_type=payload.record_type,
                        data=record_data,
                        mission_id=str(context.mission_id) if context.mission_id else None,
                        task_id=str(context.task_id),
                        commit=False,
                    )
                    persisted_record_id = str(written.get("id") or record_id)
                    crm = LightCrmRecordService(session=session)
                    opportunities = crm.list_records(
                        tenant_id=context.tenant_id,
                        record_type="opportunity",
                        filters={"contact_id": persisted_record_id},
                        limit=1,
                    )
                    # The durable projection may be created by the workflow hook
                    # during this same transaction. Query by the stable contact
                    # identity as a fallback so the action result exposes the
                    # opportunity even when the filtered projection query does
                    # not see the freshly flushed JSON field yet.
                    if not opportunities:
                        opportunities = [
                            item
                            for item in crm.list_records(
                                tenant_id=context.tenant_id,
                                record_type="opportunity",
                                query=persisted_record_id,
                                limit=10,
                            )
                            if str(item.get("contact_id") or "") == persisted_record_id
                        ][:1]
                    if not opportunities:
                        opportunity = crm.ensure_opportunity_for_contact(
                            tenant_id=context.tenant_id,
                            contact=written,
                        )
                        if opportunity is not None:
                            opportunities = [opportunity]
                    timeline = crm.list_timeline(
                        tenant_id=context.tenant_id,
                        record_type=payload.record_type,
                        record_id=record_id,
                        limit=10,
                    )
                    projections.append(
                        {
                            "contact_id": persisted_record_id,
                            "account_id": written.get("account_id"),
                            "opportunity_id": opportunities[0].get("id") if opportunities else None,
                            "activity_ids": [item.get("id") for item in timeline if item.get("id")],
                        }
                    )
                else:
                    assert provider is not None
                    written = provider.write_record(
                        tenant_id=context.tenant_id,
                        record_type=payload.record_type,
                        record_id=record_id,
                        data=record_data,
                    )
                verified = read_store.read_record(
                    tenant_id=context.tenant_id,
                    record_type=payload.record_type,
                    record_id=str(written.get("id") or record_id),
                )
                if verified != written:
                    raise ValueError(f"record.write read-back verification failed for {record_id}")
                operation = "unchanged" if existing == written else ("updated" if existing else "created")
                persisted.append({**written, "operation": operation})
                readback.append(
                    {
                        "record_type": payload.record_type,
                        "record_id": str(written.get("id") or record_id),
                        "verified": True,
                        "content_sha256": hashlib.sha256(
                            json.dumps(verified, sort_keys=True, separators=(",", ":")).encode()
                        ).hexdigest(),
                    }
                )
            if session is not None:
                session.commit()
        except Exception:
            if session is not None:
                session.rollback()
            raise
        finally:
            if session is not None:
                session.close()
        changed = [str(item["id"]) for item in persisted]
        output = {
            "internal_crm_records": persisted,
            "crm_readback_records": readback,
            "persisted_count": len(persisted),
            "readback_verified_count": len(readback),
            "crm_projection_records": projections,
            "executed_at": datetime.now(UTC).isoformat(),
        }
        summary = f"Persisted and read-back verified {len(persisted)} Ajenda internal CRM record(s)."
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
                    inspected=changed,
                    changed=changed,
                    side_effect_class=SideEffectClass.INTERNAL_WRITE,
                )
            ],
            records_inspected=changed,
            records_changed=changed,
            summary=summary,
            confidence=1.0,
        )

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
