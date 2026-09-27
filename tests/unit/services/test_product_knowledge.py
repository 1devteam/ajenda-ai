from backend.services.business_profile_record_sync import build_profile_account_record, build_profile_brief
from backend.services.ontology.product_knowledge import (
    AJENDA_PRODUCT_KNOWLEDGE,
    product_catalog_hits,
    validate_product_catalog,
)


def test_product_catalog_is_unique_and_non_authoritative() -> None:
    validate_product_catalog()
    assert AJENDA_PRODUCT_KNOWLEDGE
    assert all(item.grants_execution_authority is False for item in AJENDA_PRODUCT_KNOWLEDGE)


def test_product_catalog_hits_are_deterministic_and_provenanced() -> None:
    hits = product_catalog_hits("What can Ajenda do for CRM and GTM?")
    assert hits
    assert all(item["source"] == "ajenda_product_knowledge" for item in hits)
    assert all(item["content"]["grants_execution_authority"] is False for item in hits)


def test_product_catalog_does_not_match_unrelated_generic_query() -> None:
    assert product_catalog_hits("find roofing companies in Austin") == []


def test_tenant_product_catalog_projects_into_profile_and_crm_shelves() -> None:
    product = AJENDA_PRODUCT_KNOWLEDGE[2].model_dump(mode="json")
    facts = {"business_name": {"value": "Ajenda"}, "product_catalog": {"items": [product]}}
    brief = build_profile_brief(approved_facts=facts)
    assert brief["facts"]["product_catalog"][0]["capability_id"] == "ajenda.crm_operations"
    assert "product_catalog" in brief["categories"]["offer"]
    record = build_profile_account_record(approved_facts=facts)
    assert record is not None
    assert record["product_catalog"][0]["capability_id"] == "ajenda.crm_operations"


def test_malformed_tenant_product_entry_fails_closed() -> None:
    brief = build_profile_brief(approved_facts={"product_catalog": {"items": [{"capability_id": "unknown"}]}})
    assert "product_catalog" not in brief["facts"]


def test_duplicate_tenant_product_entries_fail_closed() -> None:
    product = AJENDA_PRODUCT_KNOWLEDGE[2].model_dump(mode="json")
    brief = build_profile_brief(approved_facts={"product_catalog": {"items": [product, product]}})
    assert "product_catalog" not in brief["facts"]
