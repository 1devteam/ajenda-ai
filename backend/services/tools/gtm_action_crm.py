"""GTM CRM upsert handler."""

import hashlib
import json
from typing import Any

from backend.repositories.email_send_idempotency_repository import EmailSendIdempotencyRepository
from backend.services.plugins.crm_client import CrmUpsertResult, _credential_secret, default_crm_client
from backend.services.tools.gtm_action_common import _make_evidence
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    CredentialReference,
    GtmCrmUpsertInput,
    SideEffectClass,
    ToolInvocation,
)


def crm_upsert_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
    inp = GtmCrmUpsertInput.model_validate(inv.input)

    # Composition binds pipeline world-state under context. Prefer qualified
    # prospects when present, enrich them with discovery fields, and preserve
    # direct/manual ``data`` is safe only for one provider record. Applying a
    # common map to multiple bound prospects can overwrite their distinct
    # identities, so multi-record invocations must carry all record-specific
    # data upstream instead.
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
        if len(bound_rows) > 1 and inp.data:
            raise ValueError(
                "multi-record CRM upsert requires record-specific upstream fields; data overlay is refused"
            )
        rows = [{**bound_rows[0], **inp.data}] if len(bound_rows) == 1 else bound_rows
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

    # An explicitly requested external provider must not be downgraded to an
    # internal CRM write if credential resolution failed or produced no secret.
    if inv.credential_reference is not None and crm_cred is None:
        raise ValueError("external CRM credential resolution failed; internal fallback refused")
    if crm_cred is not None and not _credential_secret(crm_cred):
        raise ValueError("configured external CRM credential has no secret; internal fallback refused")
    if crm_cred is not None and inv.credential_reference is None:
        raise ValueError("external CRM credential requires an invocation credential_reference for effect classification")
    if crm_cred is not None:
        raw_reference = crm_cred.get("reference") if isinstance(crm_cred, dict) else crm_cred.reference
        try:
            resolved_reference = CredentialReference.model_validate(raw_reference)
        except Exception as exc:
            raise ValueError("external CRM credential lacks a verifiable runtime reference") from exc
        if resolved_reference != inv.credential_reference:
            raise ValueError("external CRM runtime credential does not match invocation credential_reference")

    results = []
    for index, row in enumerate(rows):
        row_invocation = inv
        if len(rows) > 1 and inv.idempotency_key and inv.idempotency_key.strip():
            row_invocation = inv.model_copy(
                update={"idempotency_key": f"{inv.idempotency_key.strip()}:row:{index + 1}"}
            )
        external_write = crm_cred is not None
        # Bind a replayed receipt to the exact intended provider mutation.
        # The same key must never be accepted for a different prospect or field set.
        request_hash = (
            hashlib.sha256(
                json.dumps(
                    {"record_type": inp.record_type, "data": row},
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            if external_write
            else ""
        )
        claim_key = row_invocation.idempotency_key.strip() if row_invocation.idempotency_key else ""
        session_factory = ctx.session_factory
        if external_write and session_factory is None:
            raise ValueError("external CRM upsert requires session_factory for durable replay protection")
        if external_write:
            if not claim_key:
                raise ValueError("external CRM upsert requires idempotency_key for durable replay protection")
            assert session_factory is not None
            session = session_factory()
            try:
                claim_status, cached = EmailSendIdempotencyRepository(session).try_claim(
                    tenant_id=ctx.tenant_id,
                    action=inv.action,
                    idempotency_key=claim_key,
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
            if claim_status == "replayed":
                if not isinstance(cached, dict) or cached.get("request_hash") != request_hash:
                    raise ValueError(
                        "idempotency_key was reused for a different CRM payload or lacks a verifiable request hash"
                    )
                results.append(
                    CrmUpsertResult(
                        record_type=str((cached or {}).get("record_type") or inp.record_type),
                        record_id=str((cached or {}).get("record_id") or ""),
                        data=dict((cached or {}).get("data") or {}),
                        source=str((cached or {}).get("source") or "external_crm"),
                        real=bool((cached or {}).get("real")),
                        status=str((cached or {}).get("status") or "upserted_real"),
                        status_code=(cached or {}).get("status_code"),
                        effect_verified=bool((cached or {}).get("effect_verified")),
                        readback=(cached or {}).get("readback"),
                    )
                )
                continue
            if claim_status != "newly_claimed":
                results.append(
                    CrmUpsertResult(
                        record_type=inp.record_type,
                        record_id="",
                        data=row,
                        source="external_crm",
                        real=False,
                        status="effect_unverified",
                        error="external CRM upsert has an active or uncertain idempotency claim; automatic replay is refused",
                        effect_verified=False,
                    )
                )
                continue

        result = default_crm_client().upsert(
            context=ctx,
            record_type=inp.record_type,
            data=row,
            credential=crm_cred,
            invocation=row_invocation,
            action_name=inv.action,
        )
        if external_write and result.real and result.effect_verified:
            assert session_factory is not None
            session = session_factory()
            try:
                EmailSendIdempotencyRepository(session).complete(
                    tenant_id=ctx.tenant_id,
                    action=inv.action,
                    idempotency_key=claim_key,
                    result_payload={
                        "request_hash": request_hash,
                        "record_type": result.record_type,
                        "record_id": result.record_id,
                        "data": result.data,
                        "source": result.source,
                        "real": result.real,
                        "status": result.status,
                        "status_code": result.status_code,
                        "effect_verified": result.effect_verified,
                        "readback": result.readback,
                    },
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        elif external_write:
            # The provider may have applied the write before a timeout or an
            # unreadable response. Preserve the durable claim and make a human
            # resolve it rather than risking a duplicate on automatic retry.
            result.status = "effect_unverified"
            result.real = False
            result.effect_verified = False
            result.error = result.error or "external CRM effect is uncertain; idempotency claim retained"
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
    any_error = any(item.get("error") or item["status"] in {"error", "effect_unverified"} for item in pipeline_records)
    use_external = any(
        result.source != "ajenda_brain" and (result.real or result.status == "effect_unverified") for result in results
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
