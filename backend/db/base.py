from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, declared_attr


class Base(DeclarativeBase):
    """Declarative base with deterministic table naming."""

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805 — declared_attr.directive uses cls, not self
        return cls.__name__.lower()
