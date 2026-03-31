from __future__ import annotations

from contextvars import ContextVar

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def set_correlation_id(correlation_id: str | None) -> None:
    correlation_id_var.set(correlation_id)



def get_correlation_id() -> str | None:
    return correlation_id_var.get()
