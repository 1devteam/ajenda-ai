from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings


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

    def session_scope(self) -> Generator[Session]:
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
    def session_context(self) -> Generator[Session]:
        yield from self.session_scope()

    def tenant_session_scope(self, tenant_id: str) -> Generator[Session]:
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
    def tenant_session_context(self, tenant_id: str) -> Generator[Session]:
        yield from self.tenant_session_scope(tenant_id)

    def ping(self) -> bool:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def verify_schema_revision(self) -> None:
        """Fail before serving work when this image's Alembic head is not live."""
        from backend.db.schema_revision import verify_schema_revision

        verify_schema_revision(self._engine)

    def schema_revision_status(self) -> str:
        """Return a sanitized readiness state for the schema revision contract."""
        from backend.db.schema_revision import SchemaRevisionError

        try:
            self.verify_schema_revision()
        except SchemaRevisionError as exc:
            return exc.status
        return "ready"

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
