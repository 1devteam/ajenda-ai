"""Read-only verification that a runtime image matches its database schema.

Runtime processes never apply Alembic migrations.  They only compare the
single head bundled in their own image with the revision recorded by the
database.  The dedicated migrator remains the sole schema writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError


class SchemaRevisionError(RuntimeError):
    """The runtime cannot prove that its database schema is compatible."""

    def __init__(self, *, status: str, expected_heads: tuple[str, ...], actual_heads: tuple[str, ...] = ()) -> None:
        self.status = status
        self.expected_heads = expected_heads
        self.actual_heads = actual_heads
        if status == "behind":
            message = "database schema is behind the runtime image; run the dedicated migrator before runtime startup"
        elif status == "unavailable":
            message = "database schema revision is unavailable; run the dedicated migrator and verify its result"
        else:
            message = "runtime image must contain exactly one Alembic migration head"
        super().__init__(message)


@dataclass(frozen=True)
class SchemaRevisionCheck:
    status: str
    expected_heads: tuple[str, ...]
    actual_heads: tuple[str, ...]


@lru_cache(maxsize=1)
def expected_schema_heads() -> tuple[str, ...]:
    """Return the migration graph heads shipped with this running image."""
    repository_root = Path(__file__).resolve().parents[2]
    config = Config(str(repository_root / "alembic.ini"))
    heads = tuple(sorted(ScriptDirectory.from_config(config).get_heads()))
    if len(heads) != 1:
        raise SchemaRevisionError(status="invalid_graph", expected_heads=heads)
    return heads


def verify_schema_revision(engine: Engine) -> SchemaRevisionCheck:
    """Fail closed unless the database records exactly this image's single head."""
    expected_heads = expected_schema_heads()
    try:
        with engine.connect() as connection:
            actual_heads = tuple(
                sorted(
                    str(value)
                    for value in connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
                )
            )
    except SQLAlchemyError as exc:
        raise SchemaRevisionError(status="unavailable", expected_heads=expected_heads) from exc

    if actual_heads != expected_heads:
        raise SchemaRevisionError(
            status="behind",
            expected_heads=expected_heads,
            actual_heads=actual_heads,
        )
    return SchemaRevisionCheck(status="ready", expected_heads=expected_heads, actual_heads=actual_heads)
