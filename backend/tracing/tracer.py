from __future__ import annotations

import uuid
from dataclasses import dataclass

from backend.observability.context import get_correlation_id, get_tenant_id


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    request_id: str | None = None
    tenant_id: str | None = None


class Tracer:
    def new_context(self) -> TraceContext:
        return TraceContext(
            trace_id=uuid.uuid4().hex,
            request_id=get_correlation_id(),
            tenant_id=get_tenant_id(),
        )
