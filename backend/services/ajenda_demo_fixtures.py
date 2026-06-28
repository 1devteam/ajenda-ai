"""Live demo fixtures: Ajenda AI sells itself through the standalone brain."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.services.business_profile_record_sync import (
    build_profile_account_record,
    build_profile_contact_record,
    sync_profile_to_internal_records,
)

DEMO_ACTOR_ID = "ajenda_demo_seed"
DEMO_PROSPECT_ACCOUNT_ID = "acct-prospect-1"
DEMO_PROSPECT_CONTACT_ID = "cont-prospect-1"
DEMO_PROSPECT_OPPORTUNITY_ID = "opp-demo-1"

AJENDA_DEMO_PROFILE_FACTS: dict[str, dict[str, object]] = {
    "business_name": {"value": "Ajenda AI"},
    "website": {"value": "https://ajenda.ai"},
    "primary_contact_name": {"value": "Ajenda Operator"},
    "contact_email": {"value": "hello@ajenda.ai"},
    "service_area": {"value": "Global multi-tenant SaaS"},
    "target_customers": {
        "items": [
            "Ops leaders replacing ad-hoc AI scripts with governed missions",
            "Teams that need audit trails, leases, and tenant isolation by default",
        ]
    },
    "products_services": {
        "items": [
            "Governed mission runtime and worker dispatch",
            "Standalone Ajenda brain with hybrid retrieval",
            "Optional Gmail, HubSpot, Salesforce, and other plugins",
        ]
    },
    "operator_notes": {
        "value": (
            "Live demo tenant: Ajenda AI sells itself. Prefer internal records and "
            "hybrid retrieval. Do not send outbound email without approval."
        )
    },
}


def supplemental_demo_records() -> dict[str, dict[str, dict[str, Any]]]:
    """Sample prospect pipeline records for missions that research outbound opportunities."""
    return {
        "account": {
            DEMO_PROSPECT_ACCOUNT_ID: {
                "id": DEMO_PROSPECT_ACCOUNT_ID,
                "name": "Brightline Operations",
                "industry": "operations",
                "score": 82,
                "interest": "Evaluating Ajenda AI for governed mission automation",
                "source": "ajenda_demo",
            }
        },
        "contact": {
            DEMO_PROSPECT_CONTACT_ID: {
                "id": DEMO_PROSPECT_CONTACT_ID,
                "name": "Morgan Ellis",
                "account_id": DEMO_PROSPECT_ACCOUNT_ID,
                "role": "Director of Operations",
                "email": "morgan@brightlineops.example",
                "source": "ajenda_demo",
            }
        },
        "opportunity": {
            DEMO_PROSPECT_OPPORTUNITY_ID: {
                "id": DEMO_PROSPECT_OPPORTUNITY_ID,
                "name": "Brightline Ajenda AI pilot",
                "account_id": DEMO_PROSPECT_ACCOUNT_ID,
                "stage": "discovery",
                "product": "Ajenda AI governed runtime",
                "source": "ajenda_demo",
            }
        },
    }


def build_in_memory_demo_records() -> dict[str, dict[str, dict[str, Any]]]:
    """Deterministic in-memory provider template for unit tests and brain proofs."""
    records: dict[str, dict[str, dict[str, Any]]] = {
        record_type: {} for record_type in ("account", "contact", "opportunity", "activity", "task")
    }
    account = build_profile_account_record(approved_facts=AJENDA_DEMO_PROFILE_FACTS)
    contact = build_profile_contact_record(approved_facts=AJENDA_DEMO_PROFILE_FACTS)
    if account is not None:
        records["account"][str(account["id"])] = account
    if contact is not None:
        records["contact"][str(contact["id"])] = contact
    for record_type, bucket in supplemental_demo_records().items():
        records[record_type].update(bucket)
    return records


def seed_ajenda_live_demo(*, session: Session, tenant_id: str) -> list[str]:
    """Seed Ajenda self-selling profile truth, synced records, and sample prospects."""
    from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository

    profile_repo = BusinessProfileRepository(session)
    record_repo = TenantInternalRecordRepository(session)
    profile = profile_repo.get_or_create_active_profile(tenant_id=tenant_id)
    now = datetime.now(UTC)
    for category, approved_fact in AJENDA_DEMO_PROFILE_FACTS.items():
        profile = profile_repo.upsert_approved_fact(
            profile=profile,
            category=category,
            approved_fact=approved_fact,
            actor_id=DEMO_ACTOR_ID,
            updated_at=now,
            provenance_metadata={"source": "ajenda_demo_seed"},
        )
    synced = sync_profile_to_internal_records(
        session=session,
        tenant_id=tenant_id,
        approved_facts=profile.approved_facts if isinstance(profile.approved_facts, dict) else {},
    )
    for record_type, bucket in supplemental_demo_records().items():
        for record_id, payload in bucket.items():
            record_repo.write_record(
                tenant_id=tenant_id,
                record_type=record_type,
                record_id=record_id,
                data=payload,
            )
            synced.append(record_id)
    return synced