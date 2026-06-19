from __future__ import annotations

from contextvars import ContextVar

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)


def set_correlation_id(correlation_id: str | None) -> None:
    correlation_id_var.set(correlation_id)


def get_correlation_id() -> str | None:
    return correlation_id_var.get()


def set_tenant_id(tenant_id: str | None) -> None:
    tenant_id_var.set(tenant_id)


def get_tenant_id() -> str | None:
    return tenant_id_var.get()
