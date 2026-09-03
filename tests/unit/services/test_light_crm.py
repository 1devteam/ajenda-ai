from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.services.light_crm.records import LightCrmRecordService
from backend.services.light_crm.schemas import enrich_contact_data, normalize_email
from backend.services.light_crm.workflow import on_crm_upsert_completed, on_draft_approved


def test_normalize_email_lowercases() -> None:
    assert normalize_email("Ops@Example.COM") == "ops@example.com"


def test_enrich_contact_adds_universal_crm_envelope() -> None:
    record = enrich_contact_data({"email": "Ops@Example.COM", "tags": ["Roofing", "roofing"]})

    assert record["crm_schema_version"] == 1
    assert record["custom_fields"] == {}
    assert record["tags"] == ["roofing"]
    assert record["email"] == "ops@example.com"
    assert record["source"] == "ajenda"


def test_enrich_contact_normalizes_owner_id() -> None:
    record = enrich_contact_data({"owner_id": "  operator-1  "})

    assert record["owner_id"] == "operator-1"


def test_enrich_contact_rejects_malformed_extension_fields() -> None:
    try:
        enrich_contact_data({"custom_fields": ["not-an-object"]})
    except ValueError as exc:
        assert str(exc) == "custom_fields must be an object"
    else:
        raise AssertionError("malformed custom_fields must fail closed")


@patch("backend.services.light_crm.records.TenantInternalRecordRepository")
def test_link_records_is_idempotent_and_tenant_scoped(mock_repo_cls: MagicMock) -> None:
    repo = MagicMock()
    mock_repo_cls.return_value = repo
    repo.read_record.return_value = {"id": "present"}
    repo.write_record.return_value = {"id": "relationship-abc", "relationship_type": "primary_contact"}
    crm = LightCrmRecordService(session=MagicMock())

    first = crm.link_records(
        tenant_id="tenant-1",
        from_type="account",
        from_id="acct-1",
        relationship_type="Primary Contact",
        to_type="contact",
        to_id="contact-1",
    )
    second = crm.link_records(
        tenant_id="tenant-1",
        from_type="account",
        from_id="acct-1",
        relationship_type="Primary Contact",
        to_type="contact",
        to_id="contact-1",
    )

    assert first == second
    assert repo.write_record.call_args.kwargs["record_id"] == repo.write_record.call_args.kwargs["data"]["id"]


@patch("backend.services.light_crm.records.TenantInternalRecordRepository")
def test_link_records_rejects_missing_tenant_record(mock_repo_cls: MagicMock) -> None:
    repo = MagicMock()
    mock_repo_cls.return_value = repo
    repo.read_record.return_value = None
    crm = LightCrmRecordService(session=MagicMock())

    try:
        crm.link_records(
            tenant_id="tenant-1",
            from_type="account",
            from_id="acct-1",
            relationship_type="owns",
            to_type="contact",
            to_id="contact-1",
        )
    except ValueError as exc:
        assert str(exc) == "from record not found for tenant"
    else:
        raise AssertionError("foreign or missing records must fail closed")


@patch("backend.services.light_crm.records.TenantInternalRecordRepository")
def test_identity_upsert_contact_dedupes_by_email(mock_repo_cls: MagicMock) -> None:
    repo = MagicMock()
    mock_repo_cls.return_value = repo
    repo.find_record_id_by_field.return_value = "contact-7"
    repo.write_record.return_value = {"id": "contact-7", "email": "ops@example.com", "name": "Ops"}

    crm = LightCrmRecordService(session=MagicMock())
    saved = crm.identity_upsert(
        tenant_id="tenant-1",
        record_type="contact",
        data={"email": "ops@example.com", "firstname": "Ops", "lastname": "Lead"},
    )

    assert saved["id"] == "contact-7"
    repo.write_record.assert_called_once()
    assert repo.write_record.call_args.kwargs["record_id"] == "contact-7"


@patch("backend.services.light_crm.workflow.LightCrmRecordService")
def test_on_draft_approved_logs_activity(mock_crm_cls: MagicMock) -> None:
    crm = MagicMock()
    mock_crm_cls.return_value = crm
    crm.identity_upsert.return_value = {"id": "contact-1", "email": "ops@example.com"}
    crm.log_activity.return_value = {"id": "activity-1"}

    result = on_draft_approved(
        session=MagicMock(),
        tenant_id="tenant-1",
        artifact_id="pitch_email-abc",
        artifact_content={"to": "ops@example.com", "subject": "Pilot intro"},
        note="approved",
    )

    assert result["logged"] is True
    crm.log_activity.assert_called_once()


@patch("backend.services.light_crm.workflow.LightCrmRecordService")
def test_on_crm_upsert_completed_creates_opportunity_for_contact(mock_crm_cls: MagicMock) -> None:
    crm = MagicMock()
    mock_crm_cls.return_value = crm
    crm.ensure_opportunity_for_contact.return_value = {"id": "opportunity-1", "stage": "discovery"}

    result = on_crm_upsert_completed(
        session=MagicMock(),
        tenant_id="tenant-1",
        record_type="contact",
        record={"id": "contact-1", "email": "ops@example.com"},
    )

    assert result["logged"] is True
    assert result["opportunity_id"] == "opportunity-1"
    crm.log_activity.assert_called_once()
