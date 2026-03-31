from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
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
        session = self.session_factory()
        try:
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
