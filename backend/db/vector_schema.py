from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from backend.db.vector_base import VectorBase
from backend.domain.ephemeral_memory_chunk import EphemeralMemoryChunk  # noqa: F401

logger = logging.getLogger("ajenda.vector_schema")


def ensure_vector_schema(engine: Engine) -> None:
    """Create vector-plane tables and tenant RLS policies if missing."""
    inspector = inspect(engine)
    if not inspector.has_table("ephemeral_memory_chunks"):
        VectorBase.metadata.create_all(bind=engine, tables=[EphemeralMemoryChunk.__table__])

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
        connection.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_roles WHERE rolname = 'ajenda_admin'
                    ) THEN
                        CREATE ROLE ajenda_admin;
                    END IF;
                END
                $$;
                """
            )
        )
        connection.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_policies
                        WHERE schemaname = current_schema()
                          AND tablename = 'ephemeral_memory_chunks'
                          AND policyname = 'admin_bypass'
                    ) THEN
                        CREATE POLICY admin_bypass ON ephemeral_memory_chunks
                            AS PERMISSIVE
                            FOR ALL
                            TO ajenda_admin
                            USING (true)
                            WITH CHECK (true);
                    END IF;
                END
                $$;
                """
            )
        )
    logger.info("vector_schema_ready")