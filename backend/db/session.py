from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings


class DatabaseRuntime:
    """Owns the SQLAlchemy engine and session factory."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_engine(
                self._settings.database_url,
                pool_pre_ping=True,
                pool_size=self._settings.db_pool_size,
                max_overflow=self._settings.db_max_overflow,
                pool_timeout=self._settings.db_pool_timeout,
                pool_recycle=self._settings.db_pool_recycle,
            )
        return self._engine

    @property
    def session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                class_=Session,
            )
        return self._session_factory

    def session_scope(self) -> Generator[Session, None, None]:
        """Yield a transactional session without tenant context.

        Use this for admin operations, migrations, or any code that legitimately
        needs to operate across tenants (e.g. RuntimeMaintainer, system health).
        """
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def tenant_session_scope(self, tenant_id: str) -> Generator[Session, None, None]:
        """Yield a transactional session with Row-Level Security activated.

        Executes ``SET LOCAL app.current_tenant_id = :tenant_id`` inside the
        transaction so that PostgreSQL RLS policies can enforce tenant isolation
        at the database level. The SET LOCAL is scoped to the transaction and
        automatically cleared on commit or rollback.

        This is the companion implementation to migration 0003 which creates the
        RLS policies on the core tables. All per-tenant API request handlers
        MUST use this scope instead of ``session_scope()`` to ensure RLS is active.

        Args:
            tenant_id: The tenant identifier to set as the active RLS context.
                       Must match the tenant_id column values in the target tables.

        Example::

            with db_runtime.tenant_session_scope(tenant_id) as session:
                tasks = session.execute(select(ExecutionTask)).scalars().all()
                # RLS ensures only tasks for tenant_id are returned
        """
        session = self.session_factory()
        try:
            # Activate RLS for this transaction. SET LOCAL is scoped to the
            # current transaction and is automatically reset on commit/rollback.
            session.execute(
                text("SET LOCAL app.current_tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
