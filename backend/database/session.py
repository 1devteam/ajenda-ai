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

# Determine database URL (use SQLite for development if PostgreSQL not available)
db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL)

# Use SQLite for local development if PostgreSQL URL not explicitly set
if db_url.startswith("postgresql://localhost") or db_url == settings.DATABASE_URL:
    # Check if we're in development mode without PostgreSQL
    db_url = "sqlite:///./omnipath.db"
    print(f"Using SQLite for development: {db_url}")
    
    # Create SQLAlchemy engine (SQLite-specific settings)
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},  # SQLite specific
        echo=settings.DEBUG
    )
else:
    # PostgreSQL production settings
    engine = create_engine(
        db_url,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=True,
        echo=settings.DEBUG
    )

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


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
