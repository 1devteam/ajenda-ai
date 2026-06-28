"""Resolve tenant business context from profile + synced internal records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session as OrmSession

from backend.db.tenant_session import activate_tenant_session
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.domain.business_profile_projection import PROFILE_ACCOUNT_RECORD_ID, PROFILE_CONTACT_RECORD_ID
from backend.services.business_profile_record_sync import read_profile_list, read_profile_text
from backend.services.tools.schemas import ActionRuntimeContext

BUSINESS_CONTEXT_CACHE_KEY = "business_context"


@dataclass(frozen=True, slots=True)
class BusinessContext:
    business_name: str | None
    company: str | None
    domain: str | None
    website: str | None
    service_area: str | None
    primary_contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    target_customers: tuple[str, ...]
    products_services: tuple[str, ...]
    operator_notes: str | None
    account_record_id: str | None
    contact_record_id: str | None
    source: str


def _domain_from_website(website: str | None) -> str | None:
    if not website:
        return None
    text = website.strip()
    if not text:
        return None
    if "://" not in text:
        text = f"https://{text}"
    host = urlparse(text).hostname
    if host:
        return host.removeprefix("www.")
    return text.removeprefix("www.").split("/")[0] or None


def _context_from_facts(facts: dict[str, Any]) -> BusinessContext:
    business_name = read_profile_text(facts, "business_name", "name")
    website = read_profile_text(facts, "website")
    return BusinessContext(
        business_name=business_name,
        company=business_name,
        domain=_domain_from_website(website),
        website=website,
        service_area=read_profile_text(facts, "service_area", "business_address", "address"),
        primary_contact_name=read_profile_text(facts, "primary_contact_name"),
        contact_email=read_profile_text(facts, "contact_email"),
        contact_phone=read_profile_text(facts, "contact_phone"),
        target_customers=tuple(read_profile_list(facts, "target_customers", "customer_segments")),
        products_services=tuple(read_profile_list(facts, "products_services", "services", "offerings")),
        operator_notes=read_profile_text(facts, "operator_notes"),
        account_record_id=PROFILE_ACCOUNT_RECORD_ID if business_name or website else None,
        contact_record_id=PROFILE_CONTACT_RECORD_ID
        if read_profile_text(facts, "primary_contact_name", "contact_email", "contact_phone")
        else None,
        source="business_profile",
    )


def _session_supports_profile_lookup(session_factory: object) -> bool:
    session = session_factory()
    supported = isinstance(session, OrmSession)
    if supported:
        session.close()
    return supported


def _empty_context() -> BusinessContext:
    return BusinessContext(
        business_name=None,
        company=None,
        domain=None,
        website=None,
        service_area=None,
        primary_contact_name=None,
        contact_email=None,
        contact_phone=None,
        target_customers=(),
        products_services=(),
        operator_notes=None,
        account_record_id=None,
        contact_record_id=None,
        source="missing",
    )


def resolve_business_context(context: ActionRuntimeContext) -> BusinessContext:
    cached = context.runtime_cache.get(BUSINESS_CONTEXT_CACHE_KEY)
    if isinstance(cached, BusinessContext):
        return cached

    session_factory = context.session_factory
    if session_factory is None or not _session_supports_profile_lookup(session_factory):
        resolved = _empty_context()
    else:
        session = session_factory()
        try:
            activate_tenant_session(session, context.tenant_id)
            profile = BusinessProfileRepository(session).get_active_profile_for_tenant(tenant_id=context.tenant_id)
            facts = profile.approved_facts if profile is not None and isinstance(profile.approved_facts, dict) else {}
            resolved = _context_from_facts(facts) if facts else _empty_context()
        finally:
            session.close()

    context.runtime_cache[BUSINESS_CONTEXT_CACHE_KEY] = resolved
    return resolved


def default_company_and_domain(
    *,
    context: ActionRuntimeContext,
    company: str | None = None,
    domain: str | None = None,
) -> tuple[str, str]:
    business = resolve_business_context(context)
    final_company = (company or "").strip() or (business.company or "")
    final_domain = (domain or "").strip() or (business.domain or "")
    return final_company, final_domain