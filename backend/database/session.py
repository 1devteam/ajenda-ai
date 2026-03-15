"""
Database Session Management
Provides synchronous and asynchronous SQLAlchemy engines and session factories.

The module auto-detects the runtime environment:
  - VPS / Docker (PostgreSQL URL with non-localhost host) → asyncpg + psycopg2
  - Local dev (localhost PostgreSQL URL) → aiosqlite + SQLite

Built with Pride for Obex Blackvault
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session

from backend.config.settings import settings

# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------
_raw_url: str = os.getenv("DATABASE_URL", settings.DATABASE_URL)

_DEFAULT_LOCAL_URL = "postgresql://omnipath:omnipath@localhost:5432/omnipath"
_is_local_dev: bool = _raw_url == _DEFAULT_LOCAL_URL or _raw_url.startswith(
    "postgresql://omnipath:omnipath@localhost"
)

if _is_local_dev:
    # ── Local developer machine without a running PostgreSQL instance ──────
    _sync_url = "sqlite:///./omnipath.db"
    _async_url = "sqlite+aiosqlite:///./omnipath.db"
    print(f"[session] Local dev mode — using SQLite: {_sync_url}")
else:
    # ── Docker / VPS — PostgreSQL is available ─────────────────────────────
    _sync_url = _raw_url
    # Convert postgresql:// → postgresql+asyncpg:// for the async engine.
    # Also handle the postgres:// alias used by some hosting providers.
    _async_url = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
        "postgres://", "postgresql+asyncpg://", 1
    )

# ---------------------------------------------------------------------------
# Synchronous engine + session (used by existing CRUD routes)
# ---------------------------------------------------------------------------
if _is_local_dev:
    engine = create_engine(
        _sync_url,
        connect_args={"check_same_thread": False},
        echo=settings.DEBUG,
    )
else:
    engine = create_engine(
        _sync_url,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=True,
        echo=settings.DEBUG,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    Synchronous database session dependency for FastAPI.

    Usage::

        @router.get("/endpoint")
        async def endpoint(db: Session = Depends(get_db)):
            ...

    Yields:
        Session: SQLAlchemy synchronous database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Asynchronous engine + session (used by EventStore, CQRS, and new routes)
# ---------------------------------------------------------------------------
if _is_local_dev:
    async_engine = create_async_engine(
        _async_url,
        connect_args={"check_same_thread": False},
        echo=settings.DEBUG,
    )
else:
    async_engine = create_async_engine(
        _async_url,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=True,
        echo=settings.DEBUG,
    )

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Asynchronous database session dependency for FastAPI.

    Usage::

        @router.get("/endpoint")
        async def endpoint(db: AsyncSession = Depends(get_async_db)):
            ...

    Yields:
        AsyncSession: SQLAlchemy async database session.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for obtaining a database session outside of
    FastAPI dependency injection (e.g. background tasks, startup hooks).

    Usage::

        async with get_async_session() as session:
            result = await session.execute(...)

    Yields:
        AsyncSession: SQLAlchemy async database session.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
