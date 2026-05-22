"""Contract suite fixtures.

Contract tests must run without Docker/Testcontainers by default.
Any container-backed fixtures remain integration-only in tests/integration.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import get_settings
from backend.db.base import Base
from backend.domain import *  # noqa: F403
from backend.domain.tenant_plan import TenantPlan


@pytest.fixture(autouse=True)
def _contract_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_ENV", "test")
    monkeypatch.setenv("AJENDA_QUEUE_ADAPTER", "local")
    monkeypatch.setenv("AJENDA_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    get_settings.cache_clear()


@pytest.fixture()
def pg_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)()
    session.add(
        TenantPlan(
            slug="free",
            name="Free",
            max_missions_per_month=10,
            max_tasks_per_month=100,
            max_agents_per_fleet=2,
            max_concurrent_workers=1,
            max_api_keys=2,
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
