"""Prospect and draft assembly for the RevOps mission deliverable."""

from collections import defaultdict
from collections.abc import Mapping
from typing import Any, Literal, cast

from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.services.mission_composition.deliverable_completion import MaterializedArtifact
from backend.services.mission_composition.revops_deliverable_contracts import (
    RevOpsDraftRead,
    RevOpsObservedContactRead,
    RevOpsProspectRead,
)

_DRAFT_REVIEW_STATUSES = frozenset({"pending", "approved", "rejected", "sent"})


def _nonempty_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(item.strip() for item in value if isinstance(item, str) and item.strip()))


def _handler_result(task: ExecutionTask) -> dict[str, Any]:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    result = metadata.get("handler_result")
    return dict(result) if isinstance(result, dict) else {}


def _task_action(task: ExecutionTask) -> str | None:
    result = _handler_result(task)
    action = _nonempty_text(result.get("action"))
    if action is not None:
        return action
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    invocation = metadata.get("tool_invocation")
    if not isinstance(invocation, dict):
        return None
    return _nonempty_text(invocation.get("action"))


def _identity_key(
    row: Mapping[str, Any],
    *,
    records: Mapping[str, dict[str, Any]],
    companies: Mapping[str, set[str]],
) -> tuple[str | None, str | None, str | None]:
    prospect_id = _nonempty_text(row.get("prospect_id"))
    company = _nonempty_text(row.get("company") or row.get("company_name"))
    if prospect_id is not None:
        return f"id:{prospect_id}", prospect_id, company
    if company is None:
        return None, None, None
    normalized_company = company.casefold()
    matches = companies.get(normalized_company, set())
    if len(matches) == 1:
        key = next(iter(matches))
        existing = records.get(key, {})
        return key, _nonempty_text(existing.get("prospect_id")), company
    return f"company:{normalized_company}", None, company


def _new_prospect(*, prospect_id: str | None, identity_company: str | None) -> dict[str, Any]:
    return {
        "prospect_id": prospect_id,
        "_identity_company": identity_company,
        "company_name": None,
        "website": None,
        "product_description": None,
        "research_summary": None,
        "sources": [],
        "observed_contacts": [],
        "qualification_evidence": None,
        "ajenda_relevance": None,
        "qualification_score": None,
        "qualification_reasons": (),
        "drafts": [],
        "_conflicts": set(),
    }


def _record_for_row(
    row: Mapping[str, Any],
    *,
    records: dict[str, dict[str, Any]],
    companies: dict[str, set[str]],
    assembly_errors: list[str],
    artifact_key: str,
) -> dict[str, Any] | None:
    key, prospect_id, company = _identity_key(row, records=records, companies=companies)
    if key is None:
        assembly_errors.append(f"artifact {artifact_key!r} contains a row without prospect identity")
        return None
    record = records.setdefault(key, _new_prospect(prospect_id=prospect_id, identity_company=company))
    if prospect_id is not None and record["prospect_id"] is None:
        record["prospect_id"] = prospect_id
    if company is not None:
        record["_identity_company"] = record["_identity_company"] or company
        companies[company.casefold()].add(key)
    return record


def _set_scalar(
    record: dict[str, Any],
    *,
    field: str,
    value: Any,
    identity: str,
    assembly_errors: list[str],
) -> None:
    if value is None or value == "" or value == () or value == [] or value == {}:
        return
    if field in record["_conflicts"]:
        return
    current = record[field]
    if current is None or current == () or current == []:
        record[field] = value
        return
    if current == value:
        return
    record[field] = None if field not in {"qualification_reasons"} else ()
    record["_conflicts"].add(field)
    assembly_errors.append(f"conflicting {field} values for prospect {identity!r}")


def _artifact_rows(artifacts: Mapping[str, MaterializedArtifact], artifact_key: str) -> list[dict[str, Any]]:
    artifact = artifacts.get(artifact_key)
    if artifact is None or not isinstance(artifact.payload, list):
        return []
    return [dict(item) for item in artifact.payload if isinstance(item, dict)]


def _draft_read(
    row: Mapping[str, Any],
    *,
    mission: Mission,
    document_artifacts: Mapping[str, Mapping[str, Any]],
    assembly_errors: list[str],
) -> RevOpsDraftRead:
    artifact_id = _nonempty_text(row.get("artifact_id"))
    document = document_artifacts.get(artifact_id, {}) if artifact_id is not None else {}
    if document:
        document_mission_id = _nonempty_text(document.get("mission_id"))
        if document_mission_id is not None and document_mission_id != str(mission.id):
            assembly_errors.append(f"draft artifact {artifact_id!r} is not owned by the assembled mission")
            document = {}
    raw_content = document.get("content")
    content: Mapping[str, Any] = raw_content if isinstance(raw_content, dict) else {}
    raw_status = _nonempty_text(document.get("review_status"))
    review_status = cast(
        Literal["pending", "approved", "rejected", "sent", "unresolved"],
        raw_status if raw_status in _DRAFT_REVIEW_STATUSES else "unresolved",
    )
    if artifact_id is not None and not document:
        assembly_errors.append(f"draft artifact {artifact_id!r} could not be resolved")
    return RevOpsDraftRead(
        artifact_id=artifact_id,
        prospect_id=_nonempty_text(row.get("prospect_id")),
        company_name=_nonempty_text(row.get("company")),
        recipient=_nonempty_text(content.get("to") or row.get("recipient")),
        subject=_nonempty_text(content.get("subject") or row.get("subject")),
        body=_nonempty_text(content.get("body") or content.get("draft")),
        review_status=review_status,
        recipient_bound=row.get("recipient_bound") is True,
    )


def _assemble_prospects(
    *,
    mission: Mission,
    artifacts: Mapping[str, MaterializedArtifact],
    document_artifacts: Mapping[str, Mapping[str, Any]],
    assembly_errors: list[str],
) -> tuple[RevOpsProspectRead, ...]:
    records: dict[str, dict[str, Any]] = {}
    companies: dict[str, set[str]] = defaultdict(set)

    verified_rows = _artifact_rows(artifacts, "verified_prospect_candidates")
    candidate_sources = (
        (("verified_prospect_candidates", verified_rows),)
        if verified_rows
        else (("prospect_candidates", _artifact_rows(artifacts, "prospect_candidates")),)
    )
    for artifact_key, rows in candidate_sources:
        for row in rows:
            record = _record_for_row(
                row,
                records=records,
                companies=companies,
                assembly_errors=assembly_errors,
                artifact_key=artifact_key,
            )
            if record is None:
                continue
            identity = record["prospect_id"] or record["_identity_company"] or "unknown"
            _set_scalar(
                record,
                field="company_name",
                value=_nonempty_text(row.get("company") or row.get("company_name")),
                identity=identity,
                assembly_errors=assembly_errors,
            )
            for field in ("website", "product_description", "research_summary"):
                _set_scalar(
                    record,
                    field=field,
                    value=_nonempty_text(row.get(field)),
                    identity=identity,
                    assembly_errors=assembly_errors,
                )
            for source in _string_tuple(row.get("sources")):
                if source not in record["sources"]:
                    record["sources"].append(source)
            for raw_contact in row.get("observed_contacts", []):
                if not isinstance(raw_contact, dict):
                    continue
                contact = RevOpsObservedContactRead(
                    kind=_nonempty_text(raw_contact.get("kind")),
                    value=_nonempty_text(raw_contact.get("value")),
                    source_url=_nonempty_text(raw_contact.get("source_url")),
                    real=raw_contact.get("real") is True,
                )
                if contact not in record["observed_contacts"]:
                    record["observed_contacts"].append(contact)

    for row in _artifact_rows(artifacts, "observed_contacts"):
        record = _record_for_row(
            row,
            records=records,
            companies=companies,
            assembly_errors=assembly_errors,
            artifact_key="observed_contacts",
        )
        if record is None:
            continue
        for source in _string_tuple(row.get("sources")):
            if source not in record["sources"]:
                record["sources"].append(source)
        identity = record["prospect_id"] or record["_identity_company"] or "unknown"
        _set_scalar(
            record,
            field="website",
            value=_nonempty_text(row.get("website")),
            identity=identity,
            assembly_errors=assembly_errors,
        )
        contact = RevOpsObservedContactRead(
            kind=_nonempty_text(row.get("kind")),
            value=_nonempty_text(row.get("value")),
            source_url=_nonempty_text(row.get("source_url")),
            real=row.get("real") is True,
        )
        if contact not in record["observed_contacts"]:
            record["observed_contacts"].append(contact)

    for row in _artifact_rows(artifacts, "qualified_prospects"):
        record = _record_for_row(
            row,
            records=records,
            companies=companies,
            assembly_errors=assembly_errors,
            artifact_key="qualified_prospects",
        )
        if record is None:
            continue
        identity = record["prospect_id"] or record["_identity_company"] or "unknown"
        raw_score = row.get("score")
        score = raw_score if isinstance(raw_score, int) and not isinstance(raw_score, bool) else None
        values = {
            "company_name": _nonempty_text(row.get("company")),
            "website": _nonempty_text(row.get("website") or row.get("url")),
            "product_description": _nonempty_text(row.get("product_description") or row.get("description")),
            "research_summary": _nonempty_text(row.get("research_summary")),
            "qualification_evidence": dict(row["qualification_evidence"])
            if isinstance(row.get("qualification_evidence"), dict)
            else None,
            "ajenda_relevance": _nonempty_text(row.get("ajenda_relevance")),
            "qualification_score": score,
            "qualification_reasons": _string_tuple(row.get("reasons")),
        }
        for field, value in values.items():
            _set_scalar(
                record,
                field=field,
                value=value,
                identity=identity,
                assembly_errors=assembly_errors,
            )
        for source in _string_tuple(row.get("sources")):
            if source not in record["sources"]:
                record["sources"].append(source)

    for row in _artifact_rows(artifacts, "introduction_drafts"):
        record = _record_for_row(
            row,
            records=records,
            companies=companies,
            assembly_errors=assembly_errors,
            artifact_key="introduction_drafts",
        )
        if record is None:
            continue
        draft = _draft_read(
            row,
            mission=mission,
            document_artifacts=document_artifacts,
            assembly_errors=assembly_errors,
        )
        if draft not in record["drafts"]:
            record["drafts"].append(draft)

    assembled: list[RevOpsProspectRead] = []
    for key in sorted(records):
        record = records[key]
        assembled.append(
            RevOpsProspectRead(
                prospect_id=record["prospect_id"],
                company_name=record["company_name"],
                website=record["website"],
                product_description=record["product_description"],
                research_summary=record["research_summary"],
                sources=tuple(record["sources"]),
                observed_contacts=tuple(record["observed_contacts"]),
                qualification_evidence=record["qualification_evidence"],
                ajenda_relevance=record["ajenda_relevance"],
                qualification_score=record["qualification_score"],
                qualification_reasons=tuple(record["qualification_reasons"]),
                drafts=tuple(record["drafts"]),
            )
        )
    return tuple(assembled)
