from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
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


def _schema_database_url(base_url: str, schema: str) -> str:
    return str(make_url(base_url).update_query_dict({"options": f"-csearch_path={schema},public"}))


def _create_schema(base_url: str, schema: str) -> None:
    engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(
                text(
                    f'''
                    CREATE TABLE "{schema}".alembic_version (
                        version_num VARCHAR(32) NOT NULL,
                        CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
                    )
                    '''
                )
            )
    finally:
        engine.dispose()


def _drop_schema(base_url: str, schema: str) -> None:
    engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    finally:
        engine.dispose()


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
                WHERE schemaname = current_schema()
                  AND tablename IN ('capabilities', 'capability_adapters')
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


@pytest.mark.integration
def test_gtm_catalog_seed_round_trip_preserves_api_shapes_and_cleans_up_policies(pg_url: str) -> None:
    schema = f"gtm_seed_semantics_{uuid.uuid4().hex}"
    database_url = _schema_database_url(pg_url, schema)
    _create_schema(pg_url, schema)
    try:
        cfg = _alembic_config(database_url)
        alembic_command.upgrade(cfg, "head")
        with _session(database_url) as session:
            _assert_seed_rows_have_runtime_contract_shapes(session)
            assert _seed_policy_names(session) == set()

        # This test uses the session-scoped pg_url fixture. Keep Alembic's version
        # table and all migrated objects in the temporary schema so the downgrade
        # round trip cannot reverse or drop objects from the shared public schema.
        alembic_command.downgrade(cfg, "0020_expand_lifecycle_checks")
        with _session(database_url) as session:
            _assert_seed_rows_absent(session)
            assert _seed_policy_names(session) == set()

        alembic_command.upgrade(cfg, "head")
        with _session(database_url) as session:
            _assert_seed_rows_have_runtime_contract_shapes(session)
            assert _seed_policy_names(session) == set()
    finally:
        _drop_schema(pg_url, schema)
