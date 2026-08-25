from __future__ import annotations

import json
import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.db.tenant_session import activate_tenant_session

pytestmark = pytest.mark.integration

_TABLES = ("tenant_usage", "webhook_endpoints", "webhook_deliveries")


def _count(session: Session, table: str) -> int:
    return int(session.scalar(text(f"SELECT count(*) FROM {table}")) or 0)


def test_restored_rls_hides_usage_and_webhook_rows_across_tenants(pg_engine) -> None:
    role = f"rls_restore_test_{uuid.uuid4().hex}"
    quoted_role = f'"{role}"'
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    usage_id = uuid.uuid4()
    endpoint_id = uuid.uuid4()
    delivery_id = uuid.uuid4()

    with pg_engine.begin() as admin:
        admin.execute(text(f"CREATE ROLE {quoted_role} NOLOGIN"))
        admin.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted_role}"))
        admin.execute(text(f"GRANT SELECT, INSERT ON {', '.join(_TABLES)} TO {quoted_role}"))

    try:
        with pg_engine.connect() as connection:
            connection.execute(text(f"SET ROLE {quoted_role}"))
            session = Session(bind=connection, expire_on_commit=False)

            activate_tenant_session(session, tenant_a)
            session.execute(
                text(
                    """
                    INSERT INTO tenant_usage (id, tenant_id, billing_period_start)
                    VALUES (:id, :tenant_id, :period)
                    """
                ),
                {"id": usage_id, "tenant_id": uuid.UUID(tenant_a), "period": date.today().replace(day=1)},
            )
            session.execute(
                text(
                    """
                    INSERT INTO webhook_endpoints (id, tenant_id, url, secret_hash, event_types)
                    VALUES (:id, :tenant_id, :url, :secret_hash, ARRAY['task.completed']::varchar[])
                    """
                ),
                {
                    "id": endpoint_id,
                    "tenant_id": uuid.UUID(tenant_a),
                    "url": "https://example.test/hook",
                    "secret_hash": "test-hash",
                },
            )
            session.execute(
                text(
                    """
                    INSERT INTO webhook_deliveries (
                        id, endpoint_id, tenant_id, event_type, event_id, payload
                    ) VALUES (
                        :id, :endpoint_id, :tenant_id, :event_type, :event_id, CAST(:payload AS jsonb)
                    )
                    """
                ),
                {
                    "id": delivery_id,
                    "endpoint_id": endpoint_id,
                    "tenant_id": uuid.UUID(tenant_a),
                    "event_type": "task.completed",
                    "event_id": uuid.uuid4(),
                    "payload": json.dumps({"task_id": "task-1"}),
                },
            )
            session.commit()

            activate_tenant_session(session, tenant_b)
            assert all(_count(session, table) == 0 for table in _TABLES)

            with pytest.raises(DBAPIError):
                session.execute(
                    text(
                        """
                        INSERT INTO tenant_usage (id, tenant_id, billing_period_start)
                        VALUES (:id, :tenant_id, :period)
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "tenant_id": uuid.UUID(tenant_a),
                        "period": date.today().replace(day=1),
                    },
                )
                session.flush()
            session.rollback()

            # The rollback ends the transaction that established SET ROLE.
            # Re-enter the non-bypass role before proving unset tenant context
            # fails closed; otherwise the Testcontainers superuser bypasses RLS.
            connection.execute(text(f"SET ROLE {quoted_role}"))
            session.execute(text("RESET app.current_tenant_id"))
            assert all(_count(session, table) == 0 for table in _TABLES)
            session.close()
            connection.execute(text("RESET ROLE"))
            connection.commit()
    finally:
        with pg_engine.begin() as admin:
            admin.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_a},
            )
            admin.execute(text("DELETE FROM webhook_deliveries WHERE id = :id"), {"id": delivery_id})
            admin.execute(text("DELETE FROM webhook_endpoints WHERE id = :id"), {"id": endpoint_id})
            admin.execute(text("DELETE FROM tenant_usage WHERE id = :id"), {"id": usage_id})
            admin.execute(text(f"DROP OWNED BY {quoted_role}"))
            admin.execute(text(f"DROP ROLE IF EXISTS {quoted_role}"))
