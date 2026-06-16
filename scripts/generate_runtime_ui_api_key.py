from __future__ import annotations

import uuid

from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.domain.tenant import Tenant
from backend.services.api_key_service import ApiKeyService

settings = get_settings()
tenant_id = uuid.UUID(settings.worker_tenant_id)
runtime = DatabaseRuntime(settings)

with runtime.session_context() as session:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        tenant = Tenant(
            id=tenant_id,
            name="Runtime UI Tenant",
            slug=f"runtime-ui-{uuid.uuid4().hex[:8]}",
            plan="free",
        )
        session.add(tenant)
        session.flush()

    plaintext, record = ApiKeyService(session=session).create_key(
        tenant_id=str(tenant_id),
        scopes=(
            "execution:view",
            "execution:queue",
        ),
    )
    session.commit()

print("TENANT_ID=" + str(tenant_id))
print("API_KEY=" + record.key_id + "." + plaintext)
runtime.dispose()
