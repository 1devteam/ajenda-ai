from __future__ import annotations

import uuid
from typing import Any

from backend.repositories.retrieval_contract_repository import RetrievalContractRepository
from backend.services.business_context_resolver import resolve_business_context
from backend.services.data_plane.memory_chunk_store import resolve_memory_chunk_store
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.record_store import resolve_record_store
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    RetrievalHybridInput,
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
    inspected: list[str],
    provenance: dict[str, Any] | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="retrieval_actions",
        action_name=action,
        tool_provider=provider,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=payload,
        records_inspected=inspected,
        provenance=provenance or {},
        side_effect_class=SideEffectClass.INTERNAL_READ,
    )


def _merge_hits(*groups: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            if not isinstance(item, dict):
                continue
            key = str(item.get("id") or item.get("content") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


def retrieval_hybrid_search(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload_input = RetrievalHybridInput.model_validate(invocation.input)
    record_store = resolve_record_store(context)
    memory_store = resolve_memory_chunk_store(context)

    internal_hits: list[dict[str, Any]] = []
    for record_type in ("account", "contact", "opportunity"):
        internal_hits.extend(
            record_store.search_records(
                tenant_id=context.tenant_id,
                record_type=record_type,
                query=payload_input.query,
                filters=payload_input.filters,
                limit=payload_input.limit,
            )
        )

    keyword_hits = memory_store.keyword_search(
        tenant_id=context.tenant_id,
        query=payload_input.query,
        mission_id=payload_input.mission_id,
        limit=payload_input.limit,
    )
    vector_hits = memory_store.vector_search(
        tenant_id=context.tenant_id,
        query=payload_input.query,
        mission_id=payload_input.mission_id,
        limit=payload_input.limit,
    )

    contract_summaries: list[dict[str, Any]] = []
    contract_memory_hits: list[dict[str, Any]] = []
    if payload_input.mission_id and context.session_factory:
        session = context.session_factory()
        try:
            repo = RetrievalContractRepository(session)
            contracts = repo.list_for_mission(
                mission_id=uuid.UUID(payload_input.mission_id),
                tenant_id=context.tenant_id,
            )
            for contract in contracts:
                contract_summary = {
                    "id": str(contract.id),
                    "strategy": contract.retrieval_strategy,
                    "reason": contract.retrieval_reason,
                    "governance_constraints": contract.governance_constraints,
                    "trust_signal": contract.trust_signal,
                    "provenance_metadata": contract.provenance_metadata,
                    "status": contract.retrieval_status,
                }
                contract_summaries.append(contract_summary)
                for ref in contract.returned_memory_references or contract.memory_references or []:
                    if isinstance(ref, dict) and ref.get("memory_id"):
                        contract_memory_hits.append(
                            {
                                "id": str(ref.get("memory_id")),
                                "content": ref.get("content") or ref.get("summary") or "",
                                "source": "retrieval_contract",
                                "contract_id": str(contract.id),
                                "search_mode": "contract_reference",
                            }
                        )
        finally:
            session.close()

    normalized_internal = [
        {
            "id": str(item.get("id") or f"internal-{index}"),
            "content": item,
            "source": "tenant_internal_records",
            "search_mode": "keyword",
            "score": 0.75,
        }
        for index, item in enumerate(internal_hits, start=1)
    ]
    memories = _merge_hits(
        vector_hits,
        keyword_hits,
        contract_memory_hits,
        normalized_internal,
        limit=payload_input.limit,
    )

    search_modes = sorted(
        {
            str(item.get("search_mode"))
            for item in (vector_hits + keyword_hits + normalized_internal + contract_memory_hits)
            if isinstance(item, dict) and item.get("search_mode")
        }
    )
    business_context = resolve_business_context(context)
    provenance: dict[str, Any] = {
        "source": "hybrid_retrieval",
        "search_modes": search_modes or ["keyword"],
        "internal_record_count": len(normalized_internal),
        "memory_chunk_keyword_count": len(keyword_hits),
        "memory_chunk_vector_count": len(vector_hits),
    }
    if business_context.business_name:
        provenance["business_context"] = {
            "business_name": business_context.business_name,
            "account_record_id": business_context.account_record_id,
            "contact_record_id": business_context.contact_record_id,
            "source": business_context.source,
        }
    if contract_summaries:
        provenance["retrieval_contract_ids"] = [contract["id"] for contract in contract_summaries]
        provenance["governance_contract_count"] = len(contract_summaries)

    output = {
        "query": payload_input.query,
        "memories": memories,
        "filters": payload_input.filters,
        "retrieval_contracts": contract_summaries,
        "search_modes": provenance["search_modes"],
        "real": True,
        "plugin_required": False,
        "source": "ajenda_brain",
    }
    inspected = [str(item.get("id")) for item in memories if isinstance(item, dict) and item.get("id")]
    summary = (
        f"Hybrid retrieval found {len(memories)} governed memory hit(s) across {', '.join(provenance['search_modes'])}."
    )
    return ActionResult(
        action="retrieval.hybrid_search",
        provider="local_retrieval",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="retrieval.hybrid_search",
                provider="local_retrieval",
                summary=summary,
                payload=output,
                inspected=inspected,
                provenance=provenance,
            )
        ],
        records_inspected=inspected,
        summary=summary,
        confidence=0.9 if memories else 0.5,
    )


def register_retrieval_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="retrieval.hybrid_search",
            handler=retrieval_hybrid_search,
            side_effect_class=SideEffectClass.INTERNAL_READ,
            provider="local_retrieval",
            input_model=RetrievalHybridInput,
        )
    )
