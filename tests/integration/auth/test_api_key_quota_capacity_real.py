from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.api_key_record import ApiKeyRecordModel
from backend.domain.tenant import Tenant
from backend.services.api_key_service import ApiKeyService
from backend.services.quota_enforcement import (
    QuotaConfigurationError,
    QuotaEnforcementService,
    QuotaExceededError,
)


def _factory(pg_engine):
    return sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)


def _create_tenant_with_one_key(factory, *, tenant_id: uuid.UUID, slug: str) -> None:
    session = factory()
    try:
        session.add(Tenant(id=tenant_id, name="Quota proof", slug=slug, status="active", plan="free"))
        session.commit()
    finally:
        session.close()

    session = factory()
    try:
        activate_tenant_session(session, str(tenant_id))
        ApiKeyService(session).create_key(tenant_id=str(tenant_id))
        session.commit()
    finally:
        session.close()


def test_real_postgres_serializes_last_api_key_capacity_slot(pg_engine) -> None:
    factory = _factory(pg_engine)
    tenant_id = uuid.uuid4()
    _create_tenant_with_one_key(factory, tenant_id=tenant_id, slug=f"quota-proof-{tenant_id.hex[:12]}")
    barrier = Barrier(2)

    def contender() -> str:
        session = factory()
        try:
            activate_tenant_session(session, str(tenant_id))
            barrier.wait(timeout=5)
            try:
                QuotaEnforcementService(session).reserve_api_key_capacity(tenant_id)
                ApiKeyService(session).create_key(tenant_id=str(tenant_id))
                session.commit()
                return "created"
            except QuotaExceededError:
                session.rollback()
                return "blocked"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: contender(), range(2)))

    assert sorted(outcomes) == ["blocked", "created"]

    session = factory()
    try:
        activate_tenant_session(session, str(tenant_id))
        active = session.scalars(
            select(ApiKeyRecordModel).where(
                ApiKeyRecordModel.tenant_id == str(tenant_id),
                ApiKeyRecordModel.revoked.is_(False),
            )
        ).all()
        assert len(active) == 2
    finally:
        session.close()


def test_real_postgres_revocation_frees_capacity(pg_engine) -> None:
    factory = _factory(pg_engine)
    tenant_id = uuid.uuid4()
    _create_tenant_with_one_key(factory, tenant_id=tenant_id, slug=f"quota-revoke-{tenant_id.hex[:12]}")

    session = factory()
    try:
        activate_tenant_session(session, str(tenant_id))
        QuotaEnforcementService(session).reserve_api_key_capacity(tenant_id)
        _, second = ApiKeyService(session).create_key(tenant_id=str(tenant_id))
        session.commit()
    finally:
        session.close()

    session = factory()
    try:
        activate_tenant_session(session, str(tenant_id))
        ApiKeyService(session).revoke_key(key_id=second.key_id)
        session.commit()
    finally:
        session.close()

    session = factory()
    try:
        activate_tenant_session(session, str(tenant_id))
        QuotaEnforcementService(session).reserve_api_key_capacity(tenant_id)
        ApiKeyService(session).create_key(tenant_id=str(tenant_id))
        session.commit()
    finally:
        session.close()

    session = factory()
    try:
        activate_tenant_session(session, str(tenant_id))
        active_count = session.scalar(
            select(__import__("sqlalchemy").func.count())
            .select_from(ApiKeyRecordModel)
            .where(
                ApiKeyRecordModel.tenant_id == str(tenant_id),
                ApiKeyRecordModel.revoked.is_(False),
            )
        )
        assert active_count == 2
    finally:
        session.close()


def test_real_postgres_missing_plan_fails_closed(pg_engine) -> None:
    factory = _factory(pg_engine)
    tenant_id = uuid.uuid4()
    session = factory()
    try:
        session.add(
            Tenant(
                id=tenant_id,
                name="Missing plan proof",
                slug=f"quota-missing-{tenant_id.hex[:12]}",
                status="active",
                plan="missing-plan",
            )
        )
        session.commit()
    finally:
        session.close()

    session = factory()
    try:
        activate_tenant_session(session, str(tenant_id))
        try:
            QuotaEnforcementService(session).reserve_api_key_capacity(tenant_id)
        except QuotaConfigurationError:
            session.rollback()
        else:  # pragma: no cover - proof failure path
            raise AssertionError("missing quota plan must fail closed")
    finally:
        session.close()
