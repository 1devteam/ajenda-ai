from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings


def _safe_rollback(session: Session) -> None:
    """Rollback without masking the original request failure.

    Long external calls (for example mission interpretation) can outlive
    ``idle_in_transaction_session_timeout``. When Postgres already killed the
    connection, a naive ``session.rollback()`` raises and replaces the real
    HTTP error with a 500 Internal Server Error.
    """

    try:
        session.rollback()
    except Exception:
        try:
            session.invalidate()
        except Exception:
            pass


class DatabaseRuntime:
    def __init__(self, settings: Settings) -> None:
        engine_kwargs: dict[str, object] = {
            "future": True,
            "pool_pre_ping": True,
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout,
            "pool_recycle": settings.db_pool_recycle,
        }
        idle_timeout_ms = settings.db_idle_in_transaction_session_timeout_ms
        if idle_timeout_ms > 0:
            engine_kwargs["connect_args"] = {
                "options": f"-c idle_in_transaction_session_timeout={idle_timeout_ms}",
            }
        self._engine = create_engine(settings.database_url, **engine_kwargs)
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
            _safe_rollback(session)
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
            _safe_rollback(session)
            raise
        finally:
            session.close()

    @contextmanager
    def tenant_session_context(self, tenant_id: str) -> Generator[Session, None, None]:
        yield from self.tenant_session_scope(tenant_id)

    def ping(self) -> bool:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
