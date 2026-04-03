from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.auth.api_keys import ApiKeyHasher
from backend.auth.permissions import Permission
from backend.auth.principal import MachinePrincipal, PrincipalType
from backend.auth.rbac import RbacAuthorizer
from backend.domain.api_key_record import ApiKeyRecordModel
from backend.domain.audit_event import AuditEvent
from backend.repositories.api_key_repository import ApiKeyRepository
from backend.repositories.audit_event_repository import AuditEventRepository


@dataclass(slots=True)
class StoredApiKey:
    record: ApiKeyRecordModel


class ApiKeyService:
    def __init__(self, session: Session | None = None) -> None:
        self._hasher = ApiKeyHasher()
        self._rbac = RbacAuthorizer()
        self._session = session
        self._repo = ApiKeyRepository(session) if session is not None else None
        self._audit = AuditEventRepository(session) if session is not None else None
        self._memory_store: dict[str, StoredApiKey] = {}

    def create_key(self, *, tenant_id: str, scopes: tuple[str, ...]) -> tuple[str, ApiKeyRecordModel]:
        """Create a new API key for the given tenant.

        Returns the plaintext secret (shown once) and the persisted ApiKeyRecordModel.
        In memory-only mode (no DB session), stores in an in-process dict.
        """
        plaintext, record = self._hasher.build_record(tenant_id=tenant_id, scopes=scopes)
        mem_record = ApiKeyRecordModel(
            tenant_id=tenant_id,
            key_id=record.key_id,
            hashed_secret=record.hashed_secret,
            scopes_json=list(record.scopes),
            revoked=False,
        )
        if self._repo is not None:
            db_record = self._repo.add(mem_record)
            self._emit_audit(tenant_id=tenant_id, action="api_key_created", details=f"API key {db_record.key_id} created")
            return plaintext, db_record
        # Memory-only mode: store the ApiKeyRecordModel directly in the wrapper
        self._memory_store[record.key_id] = StoredApiKey(record=mem_record)
        return plaintext, mem_record

    def revoke_key(self, *, key_id: str) -> None:
        if self._repo is not None:
            record = self._repo.get_by_key_id(key_id)
            if record is None:
                raise ValueError("api key not found")
            self._repo.revoke(record)
            self._emit_audit(tenant_id=record.tenant_id, action="api_key_revoked", details=f"API key {record.key_id} revoked")
            return
        stored = self._memory_store.get(key_id)
        if stored is None:
            raise ValueError("api key not found")
        stored.record.revoked = True

    def authenticate_machine(self, *, tenant_id: str, key_id: str, plaintext: str) -> MachinePrincipal:
        record = self._load_record(key_id)
        if record.tenant_id != tenant_id:
            raise ValueError("cross-tenant api key use denied")
        if record.revoked:
            raise ValueError("api key revoked")
        if not self._hasher.verify(plaintext=plaintext, hashed_secret=record.hashed_secret):
            raise ValueError("invalid api key")
        permissions = self._rbac.resolve_permissions(("machine_executor",))
        self._emit_audit(tenant_id=tenant_id, action="api_key_authenticated", details=f"API key {record.key_id} used")
        return MachinePrincipal(
            subject_id=f"machine:{record.key_id}",
            tenant_id=tenant_id,
            principal_type=PrincipalType.MACHINE,
            roles=("machine_executor",),
            permissions=permissions,
            key_id=record.key_id,
        )

    def _load_record(self, key_id: str) -> ApiKeyRecordModel:
        if self._repo is not None:
            record = self._repo.get_by_key_id(key_id)
            if record is None:
                raise ValueError("api key not found")
            return record
        stored = self._memory_store.get(key_id)
        if stored is None:
            raise ValueError("api key not found")
        return stored.record

    def _emit_audit(self, *, tenant_id: str, action: str, details: str) -> None:
        if self._audit is None:
            return
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=None,
                category="auth",
                action=action,
                actor="api_key_service",
                details=details,
                payload_json={},
            )
        )
