"""Project approved Business Profile facts into tenant_internal_records."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.domain.business_profile_projection import (
    PROFILE_ACCOUNT_RECORD_ID,
    PROFILE_CONTACT_RECORD_ID,
    PROFILE_RECORD_SOURCE,
)
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.business_profile_categories import profile_category_for_field
from backend.services.ontology.product_knowledge import ProductKnowledge


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def read_profile_text(facts: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = facts.get(key)
        if isinstance(value, str):
            text = _clean_text(value)
            if text:
                return text
        if isinstance(value, dict):
            for nested in ("value", "default", "name"):
                text = _clean_text(value.get(nested))
                if text:
                    return text
    return None


def read_profile_list(facts: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        value = facts.get(key)
        items: list[str] = []
        if isinstance(value, list):
            items = [_clean_text(item) or "" for item in value]
        elif isinstance(value, dict):
            for nested in ("items", "values", "segments", "services"):
                nested_value = value.get(nested)
                if isinstance(nested_value, list):
                    items = [_clean_text(item) or "" for item in nested_value]
                    break
            if not items:
                text = _clean_text(value.get("value"))
                if text:
                    items = [part.strip() for part in text.split(",") if part.strip()]
        elif isinstance(value, str):
            text = _clean_text(value)
            if text:
                items = [part.strip() for part in text.split(",") if part.strip()]
        items = [item for item in items if item]
        if items:
            return items
    return []


def read_product_catalog(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """Read only tenant-approved, typed product entries; malformed entries fail closed."""

    value = facts.get("product_catalog")
    if isinstance(value, dict):
        value = value.get("items") or value.get("values")
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    capability_ids: set[str] = set()
    for item in value:
        try:
            if isinstance(item, dict):
                product = ProductKnowledge.model_validate(item)
                if product.capability_id in capability_ids:
                    # A duplicated canonical ID is ambiguous tenant knowledge.
                    # Reject the complete catalog rather than choosing an
                    # arbitrary definition or preserving conflicting copies.
                    return []
                capability_ids.add(product.capability_id)
                entries.append(product.model_dump(mode="json"))
        except ValidationError:
            continue
    return entries


def build_profile_brief(*, approved_facts: dict[str, Any], provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize approved profile facts into the canonical read deliverable.

    Composition and runtime retrieval must agree on the shape of business
    context.  This is deliberately deterministic: missing values are reported
    and no descriptive facts are synthesized.
    """

    field_aliases: dict[str, tuple[str, ...]] = {
        "business_name": ("business_name", "name", "company"),
        "industry": ("industry", "sector"),
        "description": ("description", "company_description", "about"),
        "products_services": ("products_services", "services", "offerings"),
        "target_customers": ("target_customers", "customer_segments"),
        "differentiators": ("differentiators", "key_differentiators", "advantages"),
        "service_area": ("service_area", "business_address", "address"),
        "operator_notes": ("operator_notes", "notes"),
    }
    brief: dict[str, Any] = {}
    missing_fields: list[str] = []
    for canonical, aliases in field_aliases.items():
        if canonical in {"products_services", "target_customers", "differentiators"}:
            value: Any = read_profile_list(approved_facts, *aliases)
        else:
            value = read_profile_text(approved_facts, *aliases)
        if value:
            brief[canonical] = value
        elif canonical in {
            "business_name",
            "description",
            "products_services",
            "target_customers",
            "differentiators",
        }:
            missing_fields.append(canonical)

    product_catalog = read_product_catalog(approved_facts)
    if product_catalog:
        brief["product_catalog"] = product_catalog

    conflicting_fields: list[str] = []
    for category, provenance_entry in (provenance or {}).items():
        if isinstance(provenance_entry, dict) and (
            provenance_entry.get("conflicting") is True or provenance_entry.get("conflict") is True
        ):
            conflicting_fields.append(str(category))

    categories: set[str] = {
        category_name for field in brief if (category_name := profile_category_for_field(field)) is not None
    }

    return {
        "facts": brief,
        "categories": {
            category: sorted(field for field in brief if profile_category_for_field(field) == category)
            for category in sorted(categories)
        },
        "missing_fields": missing_fields,
        "conflicting_fields": sorted(set(conflicting_fields)),
    }


def build_profile_account_record(*, approved_facts: dict[str, Any]) -> dict[str, Any] | None:
    business_name = read_profile_text(approved_facts, "business_name", "name")
    website = read_profile_text(approved_facts, "website")
    service_area = read_profile_text(approved_facts, "service_area", "business_address", "address")
    target_customers = read_profile_list(approved_facts, "target_customers", "customer_segments")
    products_services = read_profile_list(approved_facts, "products_services", "services", "offerings")
    if not any((business_name, website, service_area, target_customers, products_services)):
        return None
    record: dict[str, Any] = {
        "id": PROFILE_ACCOUNT_RECORD_ID,
        "source": PROFILE_RECORD_SOURCE,
        "profile_sync": True,
    }
    if business_name:
        record["name"] = business_name
    if website:
        record["website"] = website
    if service_area:
        record["service_area"] = service_area
    if target_customers:
        record["target_customers"] = target_customers
    if products_services:
        record["products_services"] = products_services
    product_catalog = read_product_catalog(approved_facts)
    if product_catalog:
        record["product_catalog"] = product_catalog
    return record


def build_profile_contact_record(*, approved_facts: dict[str, Any]) -> dict[str, Any] | None:
    contact_name = read_profile_text(approved_facts, "primary_contact_name")
    email = read_profile_text(approved_facts, "contact_email")
    phone = read_profile_text(approved_facts, "contact_phone")
    if not any((contact_name, email, phone)):
        return None
    record: dict[str, Any] = {
        "id": PROFILE_CONTACT_RECORD_ID,
        "account_id": PROFILE_ACCOUNT_RECORD_ID,
        "source": PROFILE_RECORD_SOURCE,
        "profile_sync": True,
    }
    if contact_name:
        record["name"] = contact_name
    if email:
        record["email"] = email
    if phone:
        record["phone"] = phone
    return record


def sync_profile_to_internal_records(
    *,
    session: Session,
    tenant_id: str,
    approved_facts: dict[str, Any],
) -> list[str]:
    """Upsert profile-projected account/contact records. Returns synced record ids."""
    repo = TenantInternalRecordRepository(session)
    synced: list[str] = []
    account_record = build_profile_account_record(approved_facts=approved_facts)
    if account_record is not None:
        repo.write_record(
            tenant_id=tenant_id,
            record_type="account",
            record_id=PROFILE_ACCOUNT_RECORD_ID,
            data=account_record,
        )
        synced.append(PROFILE_ACCOUNT_RECORD_ID)
    contact_record = build_profile_contact_record(approved_facts=approved_facts)
    if contact_record is not None:
        repo.write_record(
            tenant_id=tenant_id,
            record_type="contact",
            record_id=PROFILE_CONTACT_RECORD_ID,
            data=contact_record,
        )
        synced.append(PROFILE_CONTACT_RECORD_ID)
    return synced
