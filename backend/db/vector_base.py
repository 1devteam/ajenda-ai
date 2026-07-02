"""Separate SQLAlchemy metadata for the ephemeral/vector data plane."""

from sqlalchemy.orm import DeclarativeBase


class VectorBase(DeclarativeBase):
    """Base for tables stored on the vector/ephemeral database connection."""
