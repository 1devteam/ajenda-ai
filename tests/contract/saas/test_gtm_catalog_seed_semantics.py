from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command as alembic_command
from backend.api.routes.capability import _capability_to_read
from backend.api.routes.capability_adapter import _adapter_to_read
from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository

GTM_CAPABILITY_NAME = "gtm_outbound_email"
GTM_ADAPTER_NAME = "gtm_outbound_email_adapter"
GTM_VERSION = "1.0.0"


def _database_url(base_url: str, database: str) -> str:
    return str(make_url(base_url).set(database=database))


def _admin_database_url(base_url: str) -> str:
    url = make_url(base_url)
    return str(url.set(database="postgres"))


def _create_database(base_url: str, database: str) -> None:
    admin_engine = create_engine(_admin_database_url(base_url), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_roles WHERE rolname = 'ajenda_admin'
                        ) THEN
                            CREATE ROLE ajenda_admin;
                        END IF;
                    END
                    $$;
                    """
                )
            )
            conn.execute(text(f'CREATE DATABASE "{database}"'))
    finally:
        admin_engine.dispose()


def _drop_database(base_url: str, database: str) -> None:
    admin_engine = create_engine(_admin_database_url(base_url), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :database
                      AND pid <> pg_backend_pid()
                    """
                ),
                {"database": database},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
    finally:
        admin_engine.dispose()


def _alembic_config(database_url: str) -> AlembicConfig:
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@contextmanager
def _session(database_url: str) -> Iterator[Session]:
    engine = create_engine(database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_policy_names(session: Session) -> set[str]:
    return set(
        session.execute(
            text(
                """
                SELECT policyname
                FROM pg_policies
                WHERE tablename IN ('capabilities', 'capability_adapters')
                  AND policyname IN (
                      'seed_global_gtm_capabilities_policy',
                      'seed_global_gtm_capability_adapters_policy'
                  )
                """
            )
        ).scalars()
    )


def _assert_seed_rows_have_runtime_contract_shapes(session: Session) -> None:
    capability = session.execute(
        select(Capability).where(
            Capability.tenant_id.is_(None),
            Capability.name == GTM_CAPABILITY_NAME,
            Capability.version == GTM_VERSION,
        )
    ).scalar_one()
    adapter = session.execute(
        select(CapabilityAdapter).where(
            CapabilityAdapter.tenant_id.is_(None),
            CapabilityAdapter.name == GTM_ADAPTER_NAME,
            CapabilityAdapter.version == GTM_VERSION,
        )
    ).scalar_one()

    visible_capabilities = CapabilityRepository(session).list_visible_for_tenant(tenant_id="tenant_alpha")
    visible_adapters = CapabilityAdapterRepository(session).list_visible_for_tenant(tenant_id="tenant_alpha")

    assert capability in visible_capabilities
    assert adapter in visible_adapters
    assert isinstance(capability.evidence_expectations, list)
    assert all(isinstance(item, str) for item in capability.evidence_expectations)
    assert isinstance(adapter.evidence_expectations, list)
    assert all(isinstance(item, str) for item in adapter.evidence_expectations)

    capability_read = _capability_to_read(capability)
    adapter_read = _adapter_to_read(adapter)

    assert capability_read.scope == "global"
    assert capability_read.evidence_expectations == ["approval_decision", "send_outcome"]
    assert adapter_read.scope == "global"
    assert adapter_read.evidence_expectations == ["approval_decision", "delivery_outcome"]


def _assert_seed_rows_absent(session: Session) -> None:
    capability_count = session.scalar(
        select(func.count())
        .select_from(Capability)
        .where(
            Capability.tenant_id.is_(None),
            Capability.name == GTM_CAPABILITY_NAME,
            Capability.version == GTM_VERSION,
        )
    )
    adapter_count = session.scalar(
        select(func.count())
        .select_from(CapabilityAdapter)
        .where(
            CapabilityAdapter.tenant_id.is_(None),
            CapabilityAdapter.name == GTM_ADAPTER_NAME,
            CapabilityAdapter.version == GTM_VERSION,
        )
    )

    assert capability_count == 0
    assert adapter_count == 0


def test_gtm_catalog_seed_round_trip_preserves_api_shapes_and_cleans_up_policies(pg_url: str) -> None:
    database = f"ajenda_seed_semantics_{uuid.uuid4().hex}"
    database_url = _database_url(pg_url, database)
    _create_database(pg_url, database)
    try:
        cfg = _alembic_config(database_url)
        alembic_command.upgrade(cfg, "head")
        with _session(database_url) as session:
            _assert_seed_rows_have_runtime_contract_shapes(session)
            assert _seed_policy_names(session) == set()

        alembic_command.downgrade(cfg, "0020_expand_lifecycle_checks")
        with _session(database_url) as session:
            _assert_seed_rows_absent(session)
            assert _seed_policy_names(session) == set()

        alembic_command.upgrade(cfg, "head")
        with _session(database_url) as session:
            _assert_seed_rows_have_runtime_contract_shapes(session)
            assert _seed_policy_names(session) == set()
    finally:
        _drop_database(pg_url, database)
