"""Real queue and PostgreSQL admission proof for runtime-owned measurement sources."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.evidence import EvidenceRecord
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.business_understanding.measurement_source import resolve_runtime_measurement
from backend.services.business_understanding.service import (
    BusinessUnderstandingService,
    BusinessUnderstandingValidationError,
)
from backend.services.tools.evidence_bridge import CanonicalToolEvidenceError
from tests.integration.intelligence.canonical_decision_runtime import execute_canonical_action

pytestmark = pytest.mark.integration


def _snapshot(*, subject_id: str, source_version: str = "rev-1") -> dict[str, object]:
    return {
        "schema_version": 1,
        "goal": {
            "goal_id": "conversion-goal",
            "objective_key": "increase_conversion",
            "name": "Increase conversion",
            "subject_refs": [{"object_type": "opportunity", "object_id": subject_id}],
        },
        "kpis": [
            {
                "kpi_id": "conversion",
                "goal_id": "conversion-goal",
                "name": "Conversion",
                "metric": "conversion",
                "direction": "increase",
                "target_value": 1.0,
                "current_value": 0.5,
            }
        ],
        "source_version": source_version,
        "measurement_period_start": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "measurement_period_end": datetime(2026, 1, 31, tzinfo=UTC).isoformat(),
        "observed_at": datetime(2026, 2, 1, tzinfo=UTC).isoformat(),
    }


def test_canonical_record_read_admits_exact_source_measurement_without_claiming_truth(pg_engine, queue_adapter) -> None:
    tenant, foreign = str(uuid.uuid4()), str(uuid.uuid4())
    mission_id = uuid.uuid4()
    record_id = "verified-source-opportunity"
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as setup:
        setup.add_all(
            [
                Tenant(id=uuid.UUID(tenant), name="Source tenant", slug=f"source-{tenant[:8]}", plan="free"),
                Tenant(id=uuid.UUID(foreign), name="Foreign tenant", slug=f"foreign-{foreign[:8]}", plan="free"),
                Mission(id=mission_id, tenant_id=tenant, objective="Source measurement admission proof"),
            ]
        )
        setup.flush()
        TenantInternalRecordRepository(setup).write_record(
            tenant_id=tenant,
            record_type="opportunity",
            record_id=record_id,
            data={"name": "Source record", "operating_measurement": _snapshot(subject_id=record_id)},
        )
        setup.commit()

    evidence = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": record_id},
        worker_label="measurement-source-reader",
    )

    with factory() as scoped:
        activate_tenant_session(scoped, tenant)
        verified = resolve_runtime_measurement(session=scoped, tenant_id=tenant, evidence_id=evidence.id)
        assert verified.source_reference["record_id"] == record_id
        service = BusinessUnderstandingService(scoped)
        row, need = service.ingest_runtime_record_measurement(
            tenant_id=tenant, source_evidence_id=evidence.id, producer="runtime-ingress"
        )
        assert row.source_kind == "source_verified"
        assert row.source_reference["evidence_id"] == str(evidence.id)
        assert row.values[0]["current_value"] == 0.5
        assert row.confidence is None
        assert any(item["code"] == "source_read_proved_not_kpi_truth" for item in row.limitations)
        assert need is not None
        assert need.observation_references
        replay, _ = service.ingest_runtime_record_measurement(
            tenant_id=tenant, source_evidence_id=evidence.id, producer="runtime-ingress"
        )
        assert replay.id == row.id

        forged_values = verified.snapshot.kpis[0].model_copy(update={"current_value": 0.9})
        with pytest.raises(BusinessUnderstandingValidationError, match="contradicts canonical runtime snapshot"):
            service.ingest_measurement(
                tenant_id=tenant,
                goal=verified.snapshot.goal,
                kpis=[forged_values],
                subject_references=[item.model_dump(mode="json") for item in verified.snapshot.goal.subject_refs],
                source_kind="source_verified",
                source_reference=verified.source_reference,
                source_version=verified.snapshot.source_version,
                measurement_period_start=verified.snapshot.measurement_period_start,
                measurement_period_end=verified.snapshot.measurement_period_end,
                observed_at=verified.snapshot.observed_at,
                limitations=verified.limitations,
                confidence=None,
                producer="forged-values",
                runtime_source_evidence_id=evidence.id,
            )
        scoped.commit()

    # A second canonical runtime read of unchanged source content is not an
    # independent measurement or another need-originating observation.
    second_read = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": record_id},
        worker_label="measurement-source-recheck",
    )
    assert second_read.id != evidence.id
    with factory() as scoped:
        activate_tenant_session(scoped, tenant)
        replay_from_another_task, _ = BusinessUnderstandingService(scoped).ingest_runtime_record_measurement(
            tenant_id=tenant, source_evidence_id=second_read.id, producer="source-recheck"
        )
        assert replay_from_another_task.id == row.id
        assert replay_from_another_task.source_reference["evidence_id"] == str(evidence.id)
        scoped.commit()

    # A source that reuses the same revision name for changed commercial
    # values must not create another measurement identity or need history.
    changed_snapshot = _snapshot(subject_id=record_id)
    changed_kpi = dict(changed_snapshot["kpis"][0])
    changed_kpi["current_value"] = 0.75
    changed_snapshot["kpis"] = [changed_kpi]
    with factory() as setup:
        TenantInternalRecordRepository(setup).write_record(
            tenant_id=tenant,
            record_type="opportunity",
            record_id=record_id,
            data={"name": "Conflicting source revision", "operating_measurement": changed_snapshot},
        )
        setup.commit()
    conflicting_read = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": record_id},
        worker_label="same-version-different-content",
    )
    with factory() as scoped:
        activate_tenant_session(scoped, tenant)
        with pytest.raises(BusinessUnderstandingValidationError, match="source revision conflicts"):
            BusinessUnderstandingService(scoped).ingest_runtime_record_measurement(
                tenant_id=tenant, source_evidence_id=conflicting_read.id, producer="changed-source"
            )
        scoped.rollback()

    with factory() as outside:
        activate_tenant_session(outside, foreign)
        with pytest.raises(ValueError, match="inaccessible for tenant"):
            BusinessUnderstandingService(outside).ingest_runtime_record_measurement(
                tenant_id=foreign, source_evidence_id=evidence.id, producer="cross-tenant"
            )

    with factory() as tampered:
        activate_tenant_session(tampered, tenant)
        row = tampered.get(EvidenceRecord, evidence.id)
        assert row is not None
        changed = dict(row.structured_payload)
        record = dict(changed["record"])
        record["operating_measurement"] = _snapshot(subject_id=record_id, source_version="forged-later-version")
        changed["record"] = record
        row.structured_payload = changed
        tampered.flush()
        with pytest.raises(CanonicalToolEvidenceError, match="not the canonical runtime bridge projection"):
            BusinessUnderstandingService(tampered).ingest_runtime_record_measurement(
                tenant_id=tenant, source_evidence_id=evidence.id, producer="tampered-projection"
            )
        tampered.rollback()


def test_runtime_read_without_exact_measurement_contract_does_not_create_a_measurement(
    pg_engine, queue_adapter
) -> None:
    tenant = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as setup:
        setup.add(Tenant(id=uuid.UUID(tenant), name="Empty source", slug=f"empty-{tenant[:8]}", plan="free"))
        setup.add(Mission(id=mission_id, tenant_id=tenant, objective="Missing source snapshot"))
        setup.flush()
        TenantInternalRecordRepository(setup).write_record(
            tenant_id=tenant,
            record_type="opportunity",
            record_id="no-measurement",
            data={"name": "Ordinary opportunity"},
        )
        TenantInternalRecordRepository(setup).write_record(
            tenant_id=tenant,
            record_type="opportunity",
            record_id="wrong-subject",
            data={
                "name": "Unrelated source record",
                "operating_measurement": _snapshot(subject_id="different-subject"),
            },
        )
        setup.commit()

    evidence = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": "no-measurement"},
        worker_label="missing-measurement",
    )
    wrong_subject = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": "wrong-subject"},
        worker_label="wrong-subject-source",
    )
    with factory() as scoped:
        activate_tenant_session(scoped, tenant)
        service = BusinessUnderstandingService(scoped)
        with pytest.raises(ValueError, match="no explicit operating_measurement"):
            service.ingest_runtime_record_measurement(
                tenant_id=tenant, source_evidence_id=evidence.id, producer="missing-snapshot"
            )
        with pytest.raises(ValueError, match="exact read record identity"):
            service.ingest_runtime_record_measurement(
                tenant_id=tenant, source_evidence_id=wrong_subject.id, producer="wrong-source-instance"
            )


def test_two_competing_source_reads_cannot_commit_contradictory_first_revision(
    pg_engine, queue_adapter
) -> None:
    tenant = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    record_id = "concurrent-source"
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as setup:
        setup.add(Tenant(id=uuid.UUID(tenant), name="Concurrent source", slug=f"concurrent-{tenant[:8]}", plan="free"))
        setup.add(Mission(id=mission_id, tenant_id=tenant, objective="Competing immutable source revisions"))
        setup.flush()
        TenantInternalRecordRepository(setup).write_record(
            tenant_id=tenant,
            record_type="opportunity",
            record_id=record_id,
            data={"name": "First source revision", "operating_measurement": _snapshot(subject_id=record_id)},
        )
        setup.commit()
    first = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": record_id},
        worker_label="first-revision-observer",
    )
    changed = _snapshot(subject_id=record_id)
    kpi = dict(changed["kpis"][0])
    kpi["current_value"] = 0.75
    changed["kpis"] = [kpi]
    with factory() as setup:
        TenantInternalRecordRepository(setup).write_record(
            tenant_id=tenant,
            record_type="opportunity",
            record_id=record_id,
            data={"name": "Conflicting source content", "operating_measurement": changed},
        )
        setup.commit()
    second = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": record_id},
        worker_label="second-revision-observer",
    )
    ready = Barrier(2)

    def write(evidence_id: uuid.UUID) -> str:
        with factory() as scoped:
            activate_tenant_session(scoped, tenant)
            ready.wait(timeout=20)
            try:
                BusinessUnderstandingService(scoped).ingest_runtime_record_measurement(
                    tenant_id=tenant, source_evidence_id=evidence_id, producer="competing-source"
                )
                scoped.commit()
                return "committed"
            except BusinessUnderstandingValidationError as exc:
                scoped.rollback()
                assert "source revision conflicts" in str(exc)
                return "conflict_rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, (first.id, second.id)))
    assert sorted(results) == ["committed", "conflict_rejected"]
