"""Real PostgreSQL proof for Ajenda's restricted runtime database roles."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.queue import RedisQueueAdapter
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector
from backend.services.credentials.sqlalchemy_repository import SQLAlchemyCredentialRuntimeRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.operations_service import OperationsService
from backend.services.worker_runtime_service import WorkerRuntimeService

_ROLE_PASSWORDS = {
    "api": os.environ["AJENDA_TEST_API_DATABASE_PASSWORD"],
    "worker": os.environ["AJENDA_TEST_WORKER_DATABASE_PASSWORD"],
    "assurance": os.environ["AJENDA_TEST_ASSURANCE_DATABASE_PASSWORD"],
    "migrator": os.environ["AJENDA_TEST_MIGRATOR_DATABASE_PASSWORD"],
}


def _bootstrap_roles(pg_engine) -> None:
    sql = Path("deploy/sql/database_role_bootstrap.sql").read_text(encoding="utf-8")
    # psql client directives are stripped for this direct DBAPI execution.
    sql = "\n".join(line for line in sql.splitlines() if not line.startswith("\\getenv "))

    sql = (
        sql.replace(":'api_password'", f"'{_ROLE_PASSWORDS['api']}'")
        .replace(":'worker_password'", f"'{_ROLE_PASSWORDS['worker']}'")
        .replace(":'assurance_password'", f"'{_ROLE_PASSWORDS['assurance']}'")
        .replace(":'migrator_password'", f"'{_ROLE_PASSWORDS['migrator']}'")
    )
    raw_connection = pg_engine.raw_connection()
    try:
        with raw_connection.cursor() as cursor:
            cursor.execute(sql)
        raw_connection.commit()
    finally:
        raw_connection.close()


def _role_url(pg_url: str, *, username: str, password: str) -> URL:
    url = make_url(pg_url)
    return url.set(username=username, password=password)


def _seed_tenants(pg_engine) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    with pg_engine.begin() as conn:
        for tenant_id, suffix in ((tenant_a, "a"), (tenant_b, "b")):
            conn.execute(
                text("INSERT INTO tenants (id, name, slug, status, plan) VALUES (:id, :name, :slug, 'active', 'free')"),
                {"id": tenant_id, "name": f"Role test {suffix}", "slug": f"role-test-{tenant_id.hex}"},
            )
            conn.execute(
                text(
                    "INSERT INTO billing_meter_dispatches "
                    "(id, tenant_id, metric, quantity, status, attempt_count, next_attempt_at, created_at, updated_at) "
                    "VALUES (:id, :tenant_id, 'missions', 1, 'pending', 0, :now, :now, :now)"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant_id, "now": now},
            )
    return tenant_a, tenant_b


def _set_tenant(connection, tenant_id: uuid.UUID) -> None:
    connection.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant_id)}
    )


def test_runtime_roles_are_restricted_and_billing_rows_are_tenant_isolated_real(pg_engine, pg_url: str) -> None:
    tenant_a, tenant_b = _seed_tenants(pg_engine)
    api_engine = create_engine(_role_url(pg_url, username="ajenda_api", password=_ROLE_PASSWORDS["api"]))
    worker_engine = create_engine(_role_url(pg_url, username="ajenda_worker", password=_ROLE_PASSWORDS["worker"]))
    assurance_engine = create_engine(
        _role_url(pg_url, username="ajenda_assurance", password=_ROLE_PASSWORDS["assurance"])
    )
    try:
        with api_engine.begin() as conn:
            identity = conn.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
            assert identity == ("ajenda_api", False, False, False, False)
            _set_tenant(conn, tenant_a)
            assert conn.scalar(text("SELECT count(*) FROM billing_meter_dispatches")) == 1
            assert (
                conn.scalar(
                    text("SELECT count(*) FROM billing_meter_dispatches WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_b},
                )
                == 0
            )
            with pytest.raises(DBAPIError):
                conn.execute(
                    text(
                        "INSERT INTO billing_meter_dispatches "
                        "(id, tenant_id, metric, quantity, status, attempt_count, next_attempt_at) "
                        "VALUES (:id, :tenant_id, 'missions', 1, 'pending', 0, now())"
                    ),
                    {"id": uuid.uuid4(), "tenant_id": tenant_b},
                )

        with api_engine.begin() as conn:
            # SET LOCAL state ends with the transaction; pooled connections
            # therefore cannot carry Tenant A into a no-context request.
            assert conn.scalar(text("SELECT count(*) FROM billing_meter_dispatches")) == 0

        with api_engine.connect() as conn:
            # Membership is intentionally a pre-tenant authentication registry:
            # it has no tenant RLS so API login and membership selection can
            # occur before a tenant context exists.  The API identity owns
            # that read; worker and assurance denial is asserted below.
            assert (
                conn.scalar(text("SELECT has_table_privilege(current_user, 'public.tenant_members', 'SELECT')")) is True
            )

        for engine in (worker_engine, assurance_engine):
            with engine.connect() as conn:
                for table in (
                    "customer_auth_sessions",
                    "oidc_login_intents",
                    "signup_attempt_log",
                    "tenant_members",
                ):
                    with pytest.raises(DBAPIError):
                        conn.execute(text(f"SELECT count(*) FROM {table}"))
                    conn.rollback()

        for engine in (api_engine, worker_engine):
            with engine.connect() as conn:
                for statement in (
                    "CREATE TABLE runtime_role_escape (id integer)",
                    "ALTER TABLE billing_meter_dispatches DISABLE ROW LEVEL SECURITY",
                    "CREATE ROLE runtime_role_escape",
                ):
                    with pytest.raises(DBAPIError):
                        conn.execute(text(statement))
                    conn.rollback()

        with assurance_engine.begin() as conn:
            _set_tenant(conn, tenant_a)
            assert conn.scalar(text("SELECT count(*) FROM billing_meter_dispatches")) == 1
            with pytest.raises(DBAPIError):
                conn.execute(
                    text("UPDATE billing_meter_dispatches SET status = 'delivered' WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_a},
                )
    finally:
        api_engine.dispose()
        worker_engine.dispose()
        assurance_engine.dispose()


def test_worker_credential_runtime_repository_activates_tenant_rls_context_real(pg_engine, pg_url: str) -> None:
    """A fresh worker lookup must activate RLS before resolving a credential."""

    tenant_a, tenant_b = _seed_tenants(pg_engine)
    credential_id = f"credential-{uuid.uuid4().hex}"
    protector = RuntimeCredentialSecretProtector()
    with Session(pg_engine) as setup:
        setup.add(
            ProviderRuntimeCredential(
                id=f"prc-{uuid.uuid4()}",
                tenant_id=str(tenant_a),
                credential_id=credential_id,
                provider="external_crm",
                integration="hubspot",
                credential_type="api_key",
                enabled=True,
                revoked=False,
                deleted=False,
                allowed_actions=["crm.read"],
                allowed_side_effect_classes=["external_read"],
                trusted_destination_hosts=["api.hubapi.com"],
                secret_ciphertext=protector.encrypt_secret("worker-rls-test-secret"),
            )
        )
        setup.commit()

    worker_engine = create_engine(_role_url(pg_url, username="ajenda_worker", password=_ROLE_PASSWORDS["worker"]))
    worker_factory = sessionmaker(bind=worker_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    try:
        repository = SQLAlchemyCredentialRuntimeRepository(session_factory=worker_factory)
        record = repository.get_visible_for_tenant(tenant_id=str(tenant_a), credential_id=credential_id)
        assert record is not None
        assert record.tenant_id == str(tenant_a)
        assert record.credential_id == credential_id
        assert repository.get_visible_for_tenant(tenant_id=str(tenant_b), credential_id=credential_id) is None
    finally:
        worker_engine.dispose()


def test_platform_recovery_uses_scoped_rls_passes_with_api_database_role_real(
    pg_engine,
    pg_url: str,
    queue_adapter: RedisQueueAdapter,
) -> None:
    """The API role cannot bypass RLS, but platform recovery must still recover every tenant.

    This is deliberately a role-level proof: a bootstrap/admin connection can
    hide a missing RLS activation and therefore cannot establish that the
    actual API identity can execute the governed recovery path.
    """
    tenant_ids = (str(uuid.uuid4()), str(uuid.uuid4()))
    task_ids: list[uuid.UUID] = []
    setup = Session(pg_engine, expire_on_commit=False)
    try:
        for tenant_id in tenant_ids:
            setup.add(
                Tenant(
                    id=uuid.UUID(tenant_id),
                    name=f"Recovery role test {tenant_id[:8]}",
                    slug=f"recovery-role-{tenant_id[:12]}",
                    plan="free",
                )
            )
            setup.flush()
            mission = Mission(tenant_id=tenant_id, objective="Recover stale role-proof work", status="running")
            setup.add(mission)
            setup.flush()
            task = ExecutionTask(
                tenant_id=tenant_id,
                mission_id=mission.id,
                title="stale API-role recovery fixture",
                description="real PostgreSQL RLS recovery proof",
                status=ExecutionTaskState.PLANNED.value,
                metadata_json={"task_type": "echo"},
                compliance_category="operational",
                jurisdiction="US-ALL",
                requires_human_review=False,
            )
            setup.add(task)
            setup.flush()
            assert (
                ExecutionCoordinator(setup, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task.id).ok is True
            )
            task_ids.append(task.id)
        setup.commit()

        for tenant_id, _task_id in zip(tenant_ids, task_ids, strict=True):
            claimed = WorkerRuntimeService(setup, queue_adapter).claim_next_task(
                tenant_id=tenant_id,
                worker_id=f"api-role-recovery-{tenant_id[:8]}",
            )
            assert claimed is not None
            lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
            lease = setup.get(WorkerLease, lease_id)
            assert lease is not None
            assert lease.status == WorkerLeaseState.CLAIMED.value
            lease.heartbeat_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)
            setup.commit()
    finally:
        setup.close()

    api_engine = create_engine(_role_url(pg_url, username="ajenda_api", password=_ROLE_PASSWORDS["api"]))
    try:
        with api_engine.connect() as api_connection:
            assert api_connection.scalar(text("SELECT count(*) FROM worker_leases")) == 0

        with Session(api_engine, expire_on_commit=False) as api_session:
            summary = OperationsService(api_session, queue_adapter).trigger_recovery(
                actor="user:platform-recovery-test",
                actor_tenant_id=tenant_ids[0],
            )

        assert summary.expired_lease_count == 2
        assert summary.requeued_task_count == 2
        assert summary.dead_lettered_count == 0
    finally:
        api_engine.dispose()

    with Session(pg_engine) as verify:
        leases = verify.scalars(select(WorkerLease).where(WorkerLease.task_id.in_(task_ids))).all()
        tasks = verify.scalars(select(ExecutionTask).where(ExecutionTask.id.in_(task_ids))).all()
        assert {lease.status for lease in leases} == {WorkerLeaseState.EXPIRED.value}
        assert {task.status for task in tasks} == {ExecutionTaskState.QUEUED.value}
        assert {task.retry_count for task in tasks} == {1}


def test_bootstrap_hardens_existing_runtime_roles_and_removes_memberships_real(pg_engine) -> None:
    with pg_engine.begin() as connection:
        connection.execute(text("CREATE ROLE stale_privileged NOLOGIN SUPERUSER BYPASSRLS CREATEROLE"))
        connection.execute(text("ALTER ROLE ajenda_worker SUPERUSER BYPASSRLS CREATEROLE CREATEDB INHERIT"))
        connection.execute(text("GRANT stale_privileged TO ajenda_worker"))

    _bootstrap_roles(pg_engine)

    with pg_engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolinherit "
                "FROM pg_roles WHERE rolname = 'ajenda_worker'"
            )
        ).one()
        assert role == (False, False, False, False, False)
        membership_count = connection.scalar(
            text(
                "SELECT count(*) FROM pg_auth_members membership "
                "JOIN pg_roles member ON member.oid = membership.member "
                "WHERE member.rolname = 'ajenda_worker'"
            )
        )
        assert membership_count == 0
