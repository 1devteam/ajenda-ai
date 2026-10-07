from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.assurance_snapshot import AssuranceMetricState, AssuranceSnapshot
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.repositories.tenant_repository import TenantRepository
from backend.services.continuous_assurance import ContinuousAssuranceService
from backend.workers.assurance_loop import run_once

pytestmark = pytest.mark.integration


def test_continuous_assurance_persists_tenant_history_without_mutating_mission(pg_session) -> None:
    tenant_id = str(uuid.uuid4())
    other_tenant_id = str(uuid.uuid4())
    pg_session.add(
        Tenant(
            id=uuid.UUID(tenant_id),
            name="Assurance Tenant",
            slug=f"assurance-{tenant_id[:8]}",
            plan="free",
        )
    )
    pg_session.add(
        Tenant(
            id=uuid.UUID(other_tenant_id),
            name="Other Assurance Tenant",
            slug=f"assurance-other-{other_tenant_id[:8]}",
            plan="free",
        )
    )
    pg_session.flush()

    activate_tenant_session(pg_session, tenant_id)
    mission = Mission(
        tenant_id=tenant_id,
        objective="Observe runtime without mutation",
        status="completed",
        metadata_json={"sentinel": "unchanged"},
    )
    pg_session.add(mission)
    pg_session.flush()

    snapshot = ContinuousAssuranceService(pg_session).reconcile_mission(
        tenant_id=tenant_id,
        mission=mission,
    )

    assert snapshot.tenant_id == tenant_id
    assert snapshot.authority_class == "read_model"
    assert snapshot.grants_execution_authority is False
    assert snapshot.status == "incomplete"
    assert snapshot.first_divergence == "mission:execution_tasks"
    assert mission.status == "completed"
    assert mission.metadata_json == {"sentinel": "unchanged"}

    own_rows = list(pg_session.scalars(select(AssuranceSnapshot).where(AssuranceSnapshot.tenant_id == tenant_id)))
    assert [row.id for row in own_rows] == [snapshot.id]

    # Testcontainers connects as the database owner/superuser, which bypasses
    # PostgreSQL RLS even when FORCE ROW LEVEL SECURITY is enabled. Prove the
    # policy through a non-bypass role so this assertion exercises the same
    # boundary as an ordinary application role instead of producing a false
    # negative from the privileged test harness.
    rls_role = f"assurance_rls_test_{uuid.uuid4().hex}"
    pg_session.execute(text(f'CREATE ROLE "{rls_role}" NOLOGIN'))
    pg_session.execute(text(f'GRANT USAGE ON SCHEMA public TO "{rls_role}"'))
    pg_session.execute(text(f'GRANT SELECT ON assurance_snapshots TO "{rls_role}"'))
    pg_session.execute(text(f'SET LOCAL ROLE "{rls_role}"'))

    activate_tenant_session(pg_session, tenant_id)
    role_scoped_own_rows = list(pg_session.scalars(select(AssuranceSnapshot)))
    assert [row.id for row in role_scoped_own_rows] == [snapshot.id]

    activate_tenant_session(pg_session, other_tenant_id)
    cross_tenant_rows = list(pg_session.scalars(select(AssuranceSnapshot)))
    assert cross_tenant_rows == []

    pg_session.execute(text("RESET ROLE"))


def test_assurance_restart_resumes_from_durable_history_without_runtime_mutation(pg_engine, monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    session_factory = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    metric_fields = (
        "snapshot_count",
        "aligned_count",
        "incomplete_count",
        "drifted_count",
        "contradictory_count",
        "first_divergence_count",
        "calibration_sample_count",
        "calibration_aligned_count",
        "tenant_failure_count",
    )
    previous_metrics: dict[str, int] | None = None

    monkeypatch.setattr(
        TenantRepository,
        "list_active_tenant_ids",
        lambda self: [tenant_id],
    )

    with session_factory() as setup_session:
        setup_session.add(
            Tenant(
                id=uuid.UUID(tenant_id),
                name="Assurance Restart Tenant",
                slug=f"assurance-restart-{tenant_id[:8]}",
                plan="free",
            )
        )
        activate_tenant_session(setup_session, tenant_id)
        setup_session.add(
            Mission(
                id=mission_id,
                tenant_id=tenant_id,
                objective="Prove assurance restart continuity",
                status="completed",
                metadata_json={"sentinel": "restart-proof"},
            )
        )
        setup_session.commit()

    with session_factory() as metric_session:
        state = metric_session.get(AssuranceMetricState, 1)
        assert state is not None
        previous_metrics = {field: int(getattr(state, field)) for field in metric_fields}

    try:
        first_runtime = SimpleNamespace(session_factory=session_factory)
        assert run_once(first_runtime) == 1

        with session_factory() as read_session:
            first_rows = list(
                read_session.scalars(select(AssuranceSnapshot).where(AssuranceSnapshot.mission_id == mission_id))
            )
            assert len(first_rows) == 1
            first_snapshot_id = first_rows[0].id
            first_fingerprint = first_rows[0].observation_fingerprint
            mission = read_session.get(Mission, mission_id)
            assert mission is not None
            assert mission.status == "completed"
            assert mission.metadata_json == {"sentinel": "restart-proof"}

        # A new runtime object represents a restarted assurance process. Durable
        # database history, not process memory, must drive deduplication.
        restarted_runtime = SimpleNamespace(session_factory=session_factory)
        assert run_once(restarted_runtime) == 1

        with session_factory() as read_session:
            unchanged_rows = list(
                read_session.scalars(select(AssuranceSnapshot).where(AssuranceSnapshot.mission_id == mission_id))
            )
            assert [row.id for row in unchanged_rows] == [first_snapshot_id]

        # Runtime-owned state changes independently of the monitor. The next
        # assurance process must append a new observation without rewriting the
        # prior snapshot or mutating any runtime authority.
        with session_factory() as runtime_owner_session:
            mission = runtime_owner_session.get(Mission, mission_id)
            assert mission is not None
            mission.status = "failed"
            runtime_owner_session.commit()

        second_restarted_runtime = SimpleNamespace(session_factory=session_factory)
        assert run_once(second_restarted_runtime) == 1

        with session_factory() as read_session:
            changed_rows = list(
                read_session.scalars(
                    select(AssuranceSnapshot)
                    .where(AssuranceSnapshot.mission_id == mission_id)
                    .order_by(AssuranceSnapshot.observed_at.asc(), AssuranceSnapshot.id.asc())
                )
            )
            assert len(changed_rows) == 2
            assert {row.observation_fingerprint for row in changed_rows} != {first_fingerprint}
            assert first_snapshot_id in {row.id for row in changed_rows}
            mission = read_session.get(Mission, mission_id)
            assert mission is not None
            assert mission.status == "failed"
            assert mission.metadata_json == {"sentinel": "restart-proof"}
    finally:
        with session_factory() as cleanup_session:
            cleanup_session.execute(delete(AssuranceSnapshot).where(AssuranceSnapshot.mission_id == mission_id))
            cleanup_session.execute(delete(Mission).where(Mission.id == mission_id))
            cleanup_session.execute(delete(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
            if previous_metrics is not None:
                state = cleanup_session.get(AssuranceMetricState, 1)
                assert state is not None
                for field, value in previous_metrics.items():
                    setattr(state, field, value)
            cleanup_session.commit()
