from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings


class DatabaseRuntime:
    def __init__(self, settings: Settings) -> None:
        self._engine = create_engine(
            settings.database_url,
            future=True,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
        )
        self._session_factory: sessionmaker[Session] = sessionmaker(
            bind=self._engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )

    @property
    def session_factory(self) -> sessionmaker[Session]:
        return self._session_factory

    def session_scope(self) -> Generator[Session, None, None]:
        """Yield a transactional session without tenant context."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def session_context(self) -> Generator[Session, None, None]:
        yield from self.session_scope()

    def tenant_session_scope(self, tenant_id: str) -> Generator[Session, None, None]:
        """Yield a transactional session with tenant RLS context activated."""
        session = self._session_factory()
        try:
            session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def tenant_session_context(self, tenant_id: str) -> Generator[Session, None, None]:
        yield from self.tenant_session_scope(tenant_id)

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
