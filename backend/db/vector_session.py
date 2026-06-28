from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings


class VectorDatabaseRuntime:
    """Connection pool for the ephemeral/vector data plane."""

    def __init__(self, settings: Settings) -> None:
        database_url = settings.resolved_vector_database_url
        if database_url is None:
            raise ValueError("vector database is disabled")
        engine_kwargs: dict[str, object] = {
            "future": True,
            "pool_pre_ping": True,
            "pool_size": max(1, settings.vector_db_pool_size),
            "max_overflow": max(0, settings.vector_db_max_overflow),
            "pool_timeout": settings.db_pool_timeout,
            "pool_recycle": settings.db_pool_recycle,
        }
        idle_timeout_ms = settings.db_idle_in_transaction_session_timeout_ms
        if idle_timeout_ms > 0:
            engine_kwargs["connect_args"] = {
                "options": f"-c idle_in_transaction_session_timeout={idle_timeout_ms}",
            }
        self._engine = create_engine(database_url, **engine_kwargs)
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

    def ensure_schema(self) -> None:
        from backend.db.vector_schema import ensure_vector_schema

        ensure_vector_schema(self._engine)

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