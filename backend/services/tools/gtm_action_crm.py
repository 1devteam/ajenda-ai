"""GTM CRM upsert handler."""

from typing import Any

from backend.services.plugins.crm_client import default_crm_client
from backend.services.tools.gtm_action_common import _make_evidence
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    GtmCrmUpsertInput,
    SideEffectClass,
    ToolInvocation,
)

def crm_upsert_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
    inp = GtmCrmUpsertInput.model_validate(inv.input)

    # Composition binds pipeline world-state under context. Prefer qualified
    # prospects when present, enrich them with discovery fields, and preserve
    # direct/manual ``data`` as an explicit overlay for every CRM record.
    prospect_candidates = [
        dict(item) for item in (inp.context.get("prospect_candidates") or []) if isinstance(item, dict)
    ]
    qualified_prospects = [
        dict(item) for item in (inp.context.get("qualified_prospects") or []) if isinstance(item, dict)
    ]

    def identity_keys(row: dict[str, Any]) -> tuple[str, ...]:
        keys: list[str] = []
        for field in ("prospect_id", "id", "email", "domain", "company", "name"):
            value = row.get(field)
            if isinstance(value, str) and value.strip():
                keys.append(f"{field}:{value.strip().lower()}")
        return tuple(keys)

    candidates_by_key: dict[str, dict[str, Any]] = {}
    for candidate in prospect_candidates:
        for key in identity_keys(candidate):
            candidates_by_key.setdefault(key, candidate)

    bound_rows: list[dict[str, Any]] = []
    source_artifact = "direct_data"
    if qualified_prospects:
        source_artifact = "qualified_prospects"
        for qualified in qualified_prospects:
            merged: dict[str, Any] = {}
            for key in identity_keys(qualified):
                if key in candidates_by_key:
                    merged.update(candidates_by_key[key])
                    break
            merged.update(qualified)
            bound_rows.append(merged)
    elif prospect_candidates:
        source_artifact = "prospect_candidates"
        bound_rows = [dict(item) for item in prospect_candidates]

    if bound_rows:
        rows = [{**row, **inp.data} for row in bound_rows]
    else:
        rows = [dict(inp.data)]

    # Avoid repeated writes when the same upstream record appears through
    # multiple artifacts. Records without stable identity remain distinct.
    unique_rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for index, row in enumerate(rows):
        keys = identity_keys(row)
        dedupe_key = keys[0] if keys else f"row:{index}"
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        unique_rows.append(row)
    rows = unique_rows or [dict(inp.data)]

    crm_cred = None
    for key in (inv.action, "gtm.crm_upsert", "external_crm"):
        if key in getattr(ctx, "runtime_credentials", {}):
            crm_cred = ctx.runtime_credentials[key]
            break

    results = []
    for index, row in enumerate(rows):
        row_invocation = inv
        if len(rows) > 1 and inv.idempotency_key and inv.idempotency_key.strip():
            row_invocation = inv.model_copy(
                update={"idempotency_key": f"{inv.idempotency_key.strip()}:row:{index + 1}"}
            )
        result = default_crm_client().upsert(
            context=ctx,
            record_type=inp.record_type,
            data=row,
            credential=crm_cred,
            invocation=row_invocation,
            action_name=inv.action,
        )
        results.append(result)

    pipeline_records: list[dict[str, Any]] = []
    for result in results:
        record: dict[str, Any] = {
            "record_type": result.record_type,
            "id": result.record_id or f"crm_{str(ctx.task_id)[:8]}",
            "data": result.data,
            "status": result.status,
            "real": result.real,
            "source": result.source,
            "source_artifact": source_artifact,
        }
        if result.error:
            record["error"] = result.error
        if result.status_code is not None:
            record["real_response"] = {"status_code": result.status_code}
        record["effect_verified"] = bool(result.effect_verified)
        if result.readback is not None:
            record["readback"] = result.readback
        pipeline_records.append(record)

    primary = pipeline_records[0]
    statuses = {str(item["status"]) for item in pipeline_records}
    sources = {str(item["source"]) for item in pipeline_records}
    all_real = all(bool(item["real"]) and bool(item.get("effect_verified")) for item in pipeline_records)
    any_error = any(
        item.get("error") or item["status"] in {"error", "effect_unverified"} for item in pipeline_records
    )
    use_external = any(
        result.source != "ajenda_brain" and (result.real or result.status == "effect_unverified")
        for result in results
    )
    overall_status = next(iter(statuses)) if len(statuses) == 1 else ("partial_error" if any_error else "upserted")
    overall_source = next(iter(sources)) if len(sources) == 1 else "mixed"
    upserted: dict[str, Any] = {
        "record_type": primary["record_type"],
        "id": primary["id"],
        "data": primary["data"],
        "status": overall_status,
        "real": all_real,
        "source": overall_source,
        "plugin_required": use_external,
        "pipeline_records": pipeline_records,
        "record_count": len(pipeline_records),
        "source_artifact": source_artifact,
    }
    if any_error:
        upserted["error"] = "one or more CRM pipeline records failed to upsert"
    if inv.idempotency_key and all_real:
        upserted["idempotency_key"] = inv.idempotency_key
    upserted["effect_verification"] = [
        {
            "provider_record_id": item["id"],
            "verified": bool(item.get("effect_verified")),
            "readback": item.get("readback"),
        }
        for item in pipeline_records
    ]

    # The action registry owns the ActionResult provider contract. External
    # provider identity remains explicit in the output/evidence payload.
    provider = "ajenda_brain"
    side_effect = (
        SideEffectClass.EXTERNAL_WRITE if inv.credential_reference is not None else SideEffectClass.INTERNAL_WRITE
    )
    if any_error:
        summary = f"CRM pipeline upsert completed with errors ({len(pipeline_records)} record(s))"
    elif use_external:
        summary = f"External CRM pipeline upsert completed via plugin ({len(pipeline_records)} record(s))"
    else:
        summary = f"Internal CRM pipeline upsert completed in Ajenda brain ({len(pipeline_records)} record(s))"

    return ActionResult(
        action=inv.action,
        provider=provider,
        side_effect_class=side_effect,
        output=upserted,
        evidence=[
            _make_evidence(
                inv.action,
                provider,
                ctx,
                summary,
                upserted,
                side_effect_class=side_effect,
            )
        ],
        records_changed=[str(item["id"]) for item in pipeline_records if item["real"] and item.get("id")],
        summary=summary,
    )
