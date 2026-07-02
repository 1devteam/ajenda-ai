from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from backend.services.business_context_resolver import BusinessContext, default_company_and_domain
from backend.services.tools.schemas import ActionRuntimeContext


def test_default_company_and_domain_uses_cached_business_context() -> None:
    context = ActionRuntimeContext(
        tenant_id="tenant-unit",
        task_id=uuid.uuid4(),
        mission_id=None,
        worker_id="worker-1",
        lease_id="lease-1",
    )
    context.runtime_cache["business_context"] = BusinessContext(
        business_name="Ajenda AI",
        company="Ajenda AI",
        domain="ajenda.ai",
        website="https://ajenda.ai",
        service_area=None,
        primary_contact_name=None,
        contact_email=None,
        contact_phone=None,
        target_customers=(),
        products_services=(),
        operator_notes=None,
        account_record_id="profile-account-primary",
        contact_record_id=None,
        source="business_profile",
    )

    company, domain = default_company_and_domain(context=context, company="", domain=None)
    assert company == "Ajenda AI"
    assert domain == "ajenda.ai"


def test_default_company_and_domain_prefers_explicit_input() -> None:
    context = ActionRuntimeContext(
        tenant_id="tenant-unit",
        task_id=uuid.uuid4(),
        mission_id=None,
        worker_id="worker-1",
        lease_id="lease-1",
        session_factory=MagicMock(),
    )
    context.runtime_cache["business_context"] = BusinessContext(
        business_name="Ajenda AI",
        company="Ajenda AI",
        domain="ajenda.ai",
        website="https://ajenda.ai",
        service_area=None,
        primary_contact_name=None,
        contact_email=None,
        contact_phone=None,
        target_customers=(),
        products_services=(),
        operator_notes=None,
        account_record_id="profile-account-primary",
        contact_record_id=None,
        source="business_profile",
    )

    company, domain = default_company_and_domain(
        context=context,
        company="Brightline Operations",
        domain="brightlineops.example",
    )
    assert company == "Brightline Operations"
    assert domain == "brightlineops.example"
