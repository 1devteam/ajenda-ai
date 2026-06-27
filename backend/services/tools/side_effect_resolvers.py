"""Side-effect resolvers for actions whose runtime class depends on credential presence."""

from __future__ import annotations

from backend.services.tools.schemas import SideEffectClass, ToolInvocation


def credential_reference_external_read(invocation: ToolInvocation) -> SideEffectClass:
    if invocation.credential_reference is not None:
        return SideEffectClass.EXTERNAL_READ
    return SideEffectClass.INTERNAL_READ


def credential_reference_external_write(invocation: ToolInvocation) -> SideEffectClass:
    if invocation.credential_reference is not None:
        return SideEffectClass.EXTERNAL_WRITE
    return SideEffectClass.INTERNAL_WRITE