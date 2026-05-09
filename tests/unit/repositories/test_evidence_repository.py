from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from backend.domain.evidence import EvidenceRecord
from backend.repositories.evidence_repository import EvidenceRepository


def test_add_flushes_and_refreshes_evidence_record() -> None:
    record = EvidenceRecord(
        tenant_id="tenant-a",
        mission_id=uuid.uuid4(),
        evidence_type="observation",
        evidence_source="operator",
        summary="Observed expected output.",
    )
    session = MagicMock()

    result = EvidenceRepository(session).add(record)

    assert result is record
    session.add.assert_called_once_with(record)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(record)


def test_get_for_tenant_uses_tenant_scoped_query() -> None:
    tenant_id = str(uuid.uuid4())
    evidence_id = uuid.uuid4()
    record = EvidenceRecord(
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        evidence_type="artifact",
        evidence_source="adapter",
        summary="Artifact persisted.",
    )
    session = MagicMock()
    session.scalar.return_value = record

    result = EvidenceRepository(session).get_for_tenant(evidence_id=evidence_id, tenant_id=tenant_id)

    assert result is record
    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "evidence_records.id" in compiled
    assert "evidence_records.tenant_id" in compiled
    assert tenant_id in compiled


def test_list_for_mission_filters_by_tenant_and_mission() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    session = MagicMock()
    session.scalars.return_value = [MagicMock()]

    result = EvidenceRepository(session).list_for_mission(mission_id=mission_id, tenant_id=tenant_id)

    assert result == [session.scalars.return_value[0]]
    statement = session.scalars.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "evidence_records.mission_id" in compiled
    assert "evidence_records.tenant_id" in compiled
    assert tenant_id in compiled


def test_update_flushes_and_refreshes_evidence_record() -> None:
    record = EvidenceRecord(
        tenant_id="tenant-a",
        mission_id=uuid.uuid4(),
        evidence_type="validation",
        evidence_source="reviewer",
        summary="Validation complete.",
    )
    session = MagicMock()

    result = EvidenceRepository(session).update(record)

    assert result is record
    session.add.assert_called_once_with(record)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(record)
