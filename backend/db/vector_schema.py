from __future__ import annotations

import logging
import os
from typing import cast

from sqlalchemy import Table, inspect, text
from sqlalchemy.engine import Engine

from backend.db.roles import MIGRATOR_ROLE
from backend.db.vector_base import VectorBase
from backend.domain.ephemeral_memory_chunk import EphemeralMemoryChunk

logger = logging.getLogger("ajenda.vector_schema")


def ensure_vector_schema(engine: Engine) -> None:
    """Create vector-plane tables during the dedicated migration process only."""
    if os.environ.get("AJENDA_MIGRATION_CONTEXT") != "1":
        raise RuntimeError("vector schema changes are restricted to the migration process")
    inspector = inspect(engine)
    if not inspector.has_table("ephemeral_memory_chunks"):
        VectorBase.metadata.create_all(
            bind=engine,
            tables=[cast(Table, EphemeralMemoryChunk.__table__)],
        )

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE ephemeral_memory_chunks ENABLE ROW LEVEL SECURITY"))
        connection.execute(text("ALTER TABLE ephemeral_memory_chunks FORCE ROW LEVEL SECURITY"))
        connection.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_policies
                        WHERE schemaname = current_schema()
                          AND tablename = 'ephemeral_memory_chunks'
                          AND policyname = 'ephemeral_memory_chunk_isolation'
                    ) THEN
                        CREATE POLICY ephemeral_memory_chunk_isolation ON ephemeral_memory_chunks
                            AS PERMISSIVE
                            FOR ALL
                            TO PUBLIC
                            USING (tenant_id = current_setting('app.current_tenant_id', true))
                            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));
                    END IF;
                END
                $$;
                """
            )
        )
        connection.execute(text(f"ALTER TABLE ephemeral_memory_chunks OWNER TO {MIGRATOR_ROLE}"))
    logger.info("vector_schema_ready")


def verify_vector_schema(engine: Engine) -> None:
    """Verify the migrator provisioned the vector table; do not mutate it."""
    inspector = inspect(engine)
    if not inspector.has_table("ephemeral_memory_chunks"):
        raise RuntimeError("ephemeral_memory_chunks is missing; run the migrator before starting runtime services")
