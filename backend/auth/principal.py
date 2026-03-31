from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from backend.auth.permissions import Permission


class PrincipalType(StrEnum):
    USER = "user"
    MACHINE = "machine"


@dataclass(frozen=True, slots=True)
class Principal:
    subject_id: str
    tenant_id: str
    principal_type: PrincipalType
    roles: tuple[str, ...] = field(default_factory=tuple)
    permissions: frozenset[Permission] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class UserPrincipal(Principal):
    email: str | None = None


@dataclass(frozen=True, slots=True)
class MachinePrincipal(Principal):
    key_id: str | None = None
