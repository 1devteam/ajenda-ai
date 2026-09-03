from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.light_crm.schemas import (
    DEFAULT_OPPORTUNITY_STAGE,
    PIPELINE_STAGES,
    activity_payload,
    enrich_account_data,
    enrich_contact_data,
    enrich_opportunity_data,
    normalize_domain,
    normalize_email,
)


class LightCrmRecordService:
    def __init__(self, *, session: Session) -> None:
        self._repo = TenantInternalRecordRepository(session)

    def read_record(self, *, tenant_id: str, record_type: str, record_id: str) -> dict[str, Any] | None:
        return self._repo.read_record(tenant_id=tenant_id, record_type=record_type, record_id=record_id)

    def find_record_id_by_field(
        self,
        *,
        tenant_id: str,
        record_type: str,
        field: str,
        value: str,
    ) -> str | None:
        return self._repo.find_record_id_by_field(
            tenant_id=tenant_id,
            record_type=record_type,
            field=field,
            value=value,
        )

    def identity_upsert(
        self,
        *,
        tenant_id: str,
        record_type: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_type = record_type.strip().lower()
        if normalized_type in {"lead", "leads"}:
            normalized_type = "contact"
        if normalized_type in {"company", "companies"}:
            normalized_type = "account"
        if normalized_type in {"deal", "deals"}:
            normalized_type = "opportunity"

        if normalized_type == "contact":
            return self._upsert_contact(tenant_id=tenant_id, data=data)
        if normalized_type == "account":
            return self._upsert_account(tenant_id=tenant_id, data=data)
        if normalized_type == "opportunity":
            return self._upsert_opportunity(tenant_id=tenant_id, data=data)

        record_id = data.get("id") if isinstance(data.get("id"), str) else None
        return self._repo.write_record(
            tenant_id=tenant_id,
            record_type=normalized_type,
            record_id=record_id,
            data=dict(data),
        )

    def log_activity(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        activity_id = f"activity-{uuid.uuid4().hex[:12]}"
        return self._repo.write_record(
            tenant_id=tenant_id,
            record_type="activity",
            record_id=activity_id,
            data={**payload, "id": activity_id},
        )

    def link_records(
        self,
        *,
        tenant_id: str,
        from_type: str,
        from_id: str,
        relationship_type: str,
        to_type: str,
        to_id: str,
        source: str = "ajenda",
    ) -> dict[str, Any]:
        """Create an idempotent, tenant-owned relationship between CRM records."""
        normalized_from = from_type.strip().lower()
        normalized_to = to_type.strip().lower()
        normalized_relationship = relationship_type.strip().lower().replace(" ", "_")
        if not re.fullmatch(r"[a-z][a-z0-9_:-]{1,79}", normalized_relationship):
            raise ValueError("relationship_type must use lowercase identifier characters")
        if normalized_from == normalized_to and from_id == to_id:
            raise ValueError("a CRM record cannot relate to itself")
        if self.read_record(tenant_id=tenant_id, record_type=normalized_from, record_id=from_id) is None:
            raise ValueError("from record not found for tenant")
        if self.read_record(tenant_id=tenant_id, record_type=normalized_to, record_id=to_id) is None:
            raise ValueError("to record not found for tenant")
        relationship_id = (
            "relationship-"
            + hashlib.sha256(
                f"{normalized_from}:{from_id}:{normalized_relationship}:{normalized_to}:{to_id}".encode()
            ).hexdigest()[:24]
        )
        return self._repo.write_record(
            tenant_id=tenant_id,
            record_type="relationship",
            record_id=relationship_id,
            data={
                "id": relationship_id,
                "from_type": normalized_from,
                "from_id": from_id,
                "relationship_type": normalized_relationship,
                "to_type": normalized_to,
                "to_id": to_id,
                "source": source.strip() or "ajenda",
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

    def ensure_opportunity_for_contact(
        self,
        *,
        tenant_id: str,
        contact: dict[str, Any],
        stage: str = DEFAULT_OPPORTUNITY_STAGE,
    ) -> dict[str, Any] | None:
        contact_id = str(contact.get("id") or "")
        account_id = str(contact.get("account_id") or "")
        if not contact_id:
            return None
        existing = self._repo.search_records(
            tenant_id=tenant_id,
            record_type="opportunity",
            query=contact_id,
            filters={"contact_id": contact_id},
            limit=1,
        )
        if existing:
            return existing[0]
        account_name = str(contact.get("account_name") or contact.get("company") or "Prospect").strip()
        return self._upsert_opportunity(
            tenant_id=tenant_id,
            data={
                "name": f"{account_name} opportunity",
                "account_id": account_id or None,
                "contact_id": contact_id,
                "stage": stage,
                "source": "light_crm_workflow",
            },
        )

    def _upsert_contact(self, *, tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
        record = enrich_contact_data(data)
        email = normalize_email(record.get("email"))
        record_id = None
        if email:
            record_id = self.find_record_id_by_field(
                tenant_id=tenant_id,
                record_type="contact",
                field="email",
                value=email,
            )
        account_id = record.get("account_id")
        if not account_id:
            account = self._resolve_account_for_contact(tenant_id=tenant_id, record=record)
            if account is not None:
                record["account_id"] = account["id"]
        return self._repo.write_record(
            tenant_id=tenant_id,
            record_type="contact",
            record_id=record_id,
            data=record,
        )

    def _upsert_account(self, *, tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
        record = enrich_account_data(data)
        record_id = None
        domain = normalize_domain(record.get("domain"))
        if domain:
            record_id = self.find_record_id_by_field(
                tenant_id=tenant_id,
                record_type="account",
                field="domain",
                value=domain,
            )
        if record_id is None:
            name = str(record.get("name") or "").strip()
            if name:
                record_id = self.find_record_id_by_field(
                    tenant_id=tenant_id,
                    record_type="account",
                    field="name",
                    value=name.lower(),
                )
        return self._repo.write_record(
            tenant_id=tenant_id,
            record_type="account",
            record_id=record_id,
            data=record,
        )

    def _upsert_opportunity(self, *, tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
        record = enrich_opportunity_data(data)
        record_id = record.get("id") if isinstance(record.get("id"), str) else None
        if record_id is None and record.get("contact_id"):
            matches = self._repo.search_records(
                tenant_id=tenant_id,
                record_type="opportunity",
                query=str(record["contact_id"]),
                filters={"contact_id": record["contact_id"]},
                limit=1,
            )
            if matches:
                record_id = str(matches[0].get("id"))
        previous = (
            self._repo.read_record(tenant_id=tenant_id, record_type="opportunity", record_id=record_id)
            if record_id
            else None
        )
        saved = self._repo.write_record(
            tenant_id=tenant_id,
            record_type="opportunity",
            record_id=record_id,
            data=record,
        )
        previous_stage = str(previous.get("stage") or "") if previous else ""
        next_stage = str(saved.get("stage") or "")
        if previous_stage and previous_stage != next_stage:
            self.log_activity(
                tenant_id=tenant_id,
                payload=activity_payload(
                    activity_type="stage_changed",
                    subject=f"Stage moved to {next_stage}",
                    body=f"Opportunity stage changed from {previous_stage} to {next_stage}.",
                    related_type="opportunity",
                    related_id=str(saved["id"]),
                    source_action="crm.opportunity_stage_transition",
                    metadata={"from": previous_stage, "to": next_stage},
                ),
            )
        return saved

    def _resolve_account_for_contact(self, *, tenant_id: str, record: dict[str, Any]) -> dict[str, Any] | None:
        domain = normalize_domain(record.get("domain"))
        company = str(record.get("account_name") or record.get("company") or "").strip()
        if domain:
            account_id = self.find_record_id_by_field(
                tenant_id=tenant_id,
                record_type="account",
                field="domain",
                value=domain,
            )
            if account_id:
                return self._repo.read_record(tenant_id=tenant_id, record_type="account", record_id=account_id)
        if company:
            account_id = self.find_record_id_by_field(
                tenant_id=tenant_id,
                record_type="account",
                field="name",
                value=company.lower(),
            )
            if account_id:
                return self._repo.read_record(tenant_id=tenant_id, record_type="account", record_id=account_id)
            return self._upsert_account(
                tenant_id=tenant_id,
                data={"name": company, "domain": domain, "source": "light_crm_link"},
            )
        return None

    def list_timeline(
        self,
        *,
        tenant_id: str,
        record_type: str,
        record_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self._repo.list_activities_for_record(
            tenant_id=tenant_id,
            related_type=record_type,
            related_id=record_id,
            limit=limit,
        )

    def list_records(
        self,
        *,
        tenant_id: str,
        record_type: str,
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        self._repo.seed_defaults_if_empty(tenant_id=tenant_id)
        return self._repo.search_records(
            tenant_id=tenant_id,
            record_type=record_type,
            query=query,
            filters=filters,
            limit=limit,
        )

    def pipeline_summary(self, *, tenant_id: str) -> list[dict[str, Any]]:
        opportunities = self.list_records(tenant_id=tenant_id, record_type="opportunity", limit=50)
        buckets: dict[str, list[dict[str, Any]]] = {stage: [] for stage in PIPELINE_STAGES}
        for opp in opportunities:
            stage = str(opp.get("stage") or DEFAULT_OPPORTUNITY_STAGE)
            buckets.setdefault(stage, []).append(opp)
        return [
            {"stage": stage, "count": len(items), "opportunities": items[:10]}
            for stage, items in buckets.items()
            if items
        ]
