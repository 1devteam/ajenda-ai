from __future__ import annotations

from pathlib import Path


def test_ephemeral_memory_chunk_schema_defines_table_rls_and_orm_alignment() -> None:
    schema = Path("backend/db/vector_schema.py").read_text(encoding="utf-8")
    model = Path("backend/domain/ephemeral_memory_chunk.py").read_text(encoding="utf-8")

    assert "ephemeral_memory_chunks" in schema
    assert "ephemeral_memory_chunk_isolation" in schema
    assert "admin_bypass" in schema
    assert "ENABLE ROW LEVEL SECURITY" in schema
    assert "EphemeralMemoryChunk" in model
    assert "embedding_json" in model
    assert "search_text" in model