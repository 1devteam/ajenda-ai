from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

MISSION_STATES = (
    "planned",
    "approved",
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
    "archived",
)
FLEET_STATES = (
    "planned",
    "provisioning",
    "ready",
    "running",
    "paused",
    "completed",
    "failed",
    "retired",
)
AGENT_STATES = (
    "planned",
    "provisioned",
    "assigned",
    "running",
    "paused",
    "completed",
    "failed",
    "retired",
)
TASK_STATES = (
    "planned",
    "queued",
    "claimed",
    "running",
    "blocked",
    "completed",
    "failed",
    "cancelled",
    "dead_lettered",
)
BRANCH_STATES = ("open", "running", "superseded", "selected", "closed", "failed")
LEASE_STATES = ("claimed", "active", "expired", "released")


def _state_check(name: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    formatted = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"status IN ({formatted})", name=f"ck_{name}_status")


def upgrade() -> None:
    op.create_table(
        "missions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        _state_check("missions", MISSION_STATES),
    )
    op.create_index("ix_missions_tenant_id", "missions", ["tenant_id"])

    op.create_table(
        "workforce_fleets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="RESTRICT"),
        _state_check("workforce_fleets", FLEET_STATES),
    )
    op.create_index("ix_workforce_fleets_tenant_id", "workforce_fleets", ["tenant_id"])
    op.create_index("ix_workforce_fleets_mission_id", "workforce_fleets", ["mission_id"])

    op.create_table(
        "user_workforce_agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fleet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("role_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["fleet_id"], ["workforce_fleets.id"], ondelete="RESTRICT"),
        _state_check("user_workforce_agents", AGENT_STATES),
    )
    op.create_index("ix_user_workforce_agents_tenant_id", "user_workforce_agents", ["tenant_id"])
    op.create_index("ix_user_workforce_agents_mission_id", "user_workforce_agents", ["mission_id"])
    op.create_index("ix_user_workforce_agents_fleet_id", "user_workforce_agents", ["fleet_id"])

    op.create_table(
        "execution_branches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_branch_id"], ["execution_branches.id"], ondelete="RESTRICT"),
        _state_check("execution_branches", BRANCH_STATES),
    )
    op.create_index("ix_execution_branches_tenant_id", "execution_branches", ["tenant_id"])
    op.create_index("ix_execution_branches_mission_id", "execution_branches", ["mission_id"])
    op.create_index("ix_execution_branches_parent_branch_id", "execution_branches", ["parent_branch_id"])

    op.create_table(
        "execution_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fleet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["fleet_id"], ["workforce_fleets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["execution_branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_agent_id"], ["user_workforce_agents.id"], ondelete="RESTRICT"),
        _state_check("execution_tasks", TASK_STATES),
    )
    op.create_index("ix_execution_tasks_tenant_id", "execution_tasks", ["tenant_id"])
    op.create_index("ix_execution_tasks_mission_id", "execution_tasks", ["mission_id"])
    op.create_index("ix_execution_tasks_fleet_id", "execution_tasks", ["fleet_id"])
    op.create_index("ix_execution_tasks_branch_id", "execution_tasks", ["branch_id"])
    op.create_index("ix_execution_tasks_assigned_agent_id", "execution_tasks", ["assigned_agent_id"])

    op.create_table(
        "worker_leases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("holder_identity", sa.String(length=255), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["execution_tasks.id"], ondelete="RESTRICT"),
        _state_check("worker_leases", LEASE_STATES),
    )
    op.create_index("ix_worker_leases_tenant_id", "worker_leases", ["tenant_id"])
    op.create_index("ix_worker_leases_task_id", "worker_leases", ["task_id"])

    op.create_table(
        "governance_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_governance_events_tenant_id", "governance_events", ["tenant_id"])
    op.create_index("ix_governance_events_mission_id", "governance_events", ["mission_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_mission_id", "audit_events", ["mission_id"])

    op.create_table(
        "lineage_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fleet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("worker_lease_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("relationship_type", sa.String(length=128), nullable=False),
        sa.Column("relationship_reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["fleet_id"], ["workforce_fleets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["execution_tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["execution_branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["worker_lease_id"], ["worker_leases.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_lineage_records_tenant_id", "lineage_records", ["tenant_id"])
    op.create_index("ix_lineage_records_mission_id", "lineage_records", ["mission_id"])
    op.create_index("ix_lineage_records_fleet_id", "lineage_records", ["fleet_id"])
    op.create_index("ix_lineage_records_task_id", "lineage_records", ["task_id"])
    op.create_index("ix_lineage_records_branch_id", "lineage_records", ["branch_id"])
    op.create_index("ix_lineage_records_worker_lease_id", "lineage_records", ["worker_lease_id"])


def downgrade() -> None:
    op.drop_index("ix_lineage_records_worker_lease_id", table_name="lineage_records")
    op.drop_index("ix_lineage_records_branch_id", table_name="lineage_records")
    op.drop_index("ix_lineage_records_task_id", table_name="lineage_records")
    op.drop_index("ix_lineage_records_fleet_id", table_name="lineage_records")
    op.drop_index("ix_lineage_records_mission_id", table_name="lineage_records")
    op.drop_index("ix_lineage_records_tenant_id", table_name="lineage_records")
    op.drop_table("lineage_records")
    op.drop_index("ix_audit_events_mission_id", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_governance_events_mission_id", table_name="governance_events")
    op.drop_index("ix_governance_events_tenant_id", table_name="governance_events")
    op.drop_table("governance_events")
    op.drop_index("ix_worker_leases_task_id", table_name="worker_leases")
    op.drop_index("ix_worker_leases_tenant_id", table_name="worker_leases")
    op.drop_table("worker_leases")
    op.drop_index("ix_execution_tasks_assigned_agent_id", table_name="execution_tasks")
    op.drop_index("ix_execution_tasks_branch_id", table_name="execution_tasks")
    op.drop_index("ix_execution_tasks_fleet_id", table_name="execution_tasks")
    op.drop_index("ix_execution_tasks_mission_id", table_name="execution_tasks")
    op.drop_index("ix_execution_tasks_tenant_id", table_name="execution_tasks")
    op.drop_table("execution_tasks")
    op.drop_index("ix_execution_branches_parent_branch_id", table_name="execution_branches")
    op.drop_index("ix_execution_branches_mission_id", table_name="execution_branches")
    op.drop_index("ix_execution_branches_tenant_id", table_name="execution_branches")
    op.drop_table("execution_branches")
    op.drop_index("ix_user_workforce_agents_fleet_id", table_name="user_workforce_agents")
    op.drop_index("ix_user_workforce_agents_mission_id", table_name="user_workforce_agents")
    op.drop_index("ix_user_workforce_agents_tenant_id", table_name="user_workforce_agents")
    op.drop_table("user_workforce_agents")
    op.drop_index("ix_workforce_fleets_mission_id", table_name="workforce_fleets")
    op.drop_index("ix_workforce_fleets_tenant_id", table_name="workforce_fleets")
    op.drop_table("workforce_fleets")
    op.drop_index("ix_missions_tenant_id", table_name="missions")
    op.drop_table("missions")
