"""
Database Session Management
Provides SQLAlchemy engine and session factory

Built with Pride for Obex Blackvault
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from backend.config.settings import settings
import os

# Determine database URL — environment variable takes precedence over settings default.
# pydantic-settings already merges .env into settings, so settings.DATABASE_URL
# reflects the .env value. We read from os.getenv directly to get the raw env var,
# falling back to the settings value (which itself may come from .env).
db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL)

# Use SQLite ONLY when the URL explicitly points to localhost PostgreSQL
# (i.e. a developer running without Docker). In all other cases — including
# Docker deployments where the host is a service name like 'postgres' — use
# the PostgreSQL URL as-is.
_DEFAULT_LOCAL_URL = "postgresql://omnipath:omnipath@localhost:5432/omnipath"

if db_url == _DEFAULT_LOCAL_URL or db_url.startswith("postgresql://omnipath:omnipath@localhost"):
    # Developer running locally without a PostgreSQL instance — fall back to SQLite
    db_url = "sqlite:///./omnipath.db"
    print(f"Using SQLite for development: {db_url}")

    # Create SQLAlchemy engine (SQLite-specific settings)
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},  # SQLite specific
        echo=settings.DEBUG,
    )
else:
    # PostgreSQL — production / staging / any non-default URL
    engine = create_engine(
        db_url,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=True,
        echo=settings.DEBUG,
    )

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    Database session dependency for FastAPI

    Usage:
        @router.get("/endpoint")
        async def endpoint(db: Session = Depends(get_db)):
            # Use db session
            pass

    Yields:
        Session: SQLAlchemy database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
