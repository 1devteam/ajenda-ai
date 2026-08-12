"""Add JSONB GIN index for knowledge retrieval candidate discovery.

Revision ID: 0038_knowledge_retrieval
Revises: 0037_knowledge_ledger
"""

from alembic import op

revision = "0038_knowledge_retrieval"
down_revision = "0037_knowledge_ledger"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_knowledge_artifact_proposition_payload_gin"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "knowledge_artifact_records",
        ["proposition_payload"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"proposition_payload": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="knowledge_artifact_records")
