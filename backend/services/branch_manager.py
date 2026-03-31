from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionBranchState
from backend.domain.execution_branch import ExecutionBranch
from backend.domain.lineage_record import LineageRecord
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.execution_branch_repository import ExecutionBranchRepository
from backend.repositories.lineage_record_repository import LineageRecordRepository
from backend.runtime.transitions import transition_branch


class BranchManager:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._branches = ExecutionBranchRepository(session)
        self._audit = AuditEventRepository(session)
        self._lineage = LineageRecordRepository(session)

    def create_branch(
        self,
        *,
        tenant_id: str,
        mission_id: uuid.UUID,
        parent_branch_id: uuid.UUID | None,
        reason: str,
    ) -> ExecutionBranch:
        branch = self._branches.add(
            ExecutionBranch(
                tenant_id=tenant_id,
                mission_id=mission_id,
                parent_branch_id=parent_branch_id,
                status=ExecutionBranchState.OPEN.value,
                reason=reason,
            )
        )
        self._lineage.append(
            LineageRecord(
                tenant_id=tenant_id,
                mission_id=mission_id,
                branch_id=branch.id,
                relationship_type="branch_created",
                relationship_reason=reason,
                metadata_json={"parent_branch_id": str(parent_branch_id) if parent_branch_id else None},
            )
        )
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=mission_id,
                category="branch",
                action="created",
                actor="branch_manager",
                details=reason,
                payload_json={"branch_id": str(branch.id)},
            )
        )
        return branch

    def mark_running(self, *, tenant_id: str, branch_id: uuid.UUID) -> ExecutionBranch:
        branch = self._require_branch(branch_id=branch_id, tenant_id=tenant_id)
        transition_branch(branch, ExecutionBranchState.RUNNING)
        self._session.flush()
        return branch

    def select_branch(self, *, tenant_id: str, branch_id: uuid.UUID) -> ExecutionBranch:
        branch = self._require_branch(branch_id=branch_id, tenant_id=tenant_id)
        transition_branch(branch, ExecutionBranchState.SELECTED)
        self._session.flush()
        return branch

    def supersede_branch(self, *, tenant_id: str, branch_id: uuid.UUID) -> ExecutionBranch:
        branch = self._require_branch(branch_id=branch_id, tenant_id=tenant_id)
        transition_branch(branch, ExecutionBranchState.SUPERSEDED)
        self._session.flush()
        return branch

    def close_branch(self, *, tenant_id: str, branch_id: uuid.UUID) -> ExecutionBranch:
        branch = self._require_branch(branch_id=branch_id, tenant_id=tenant_id)
        transition_branch(branch, ExecutionBranchState.CLOSED)
        self._session.flush()
        return branch

    def fail_branch(self, *, tenant_id: str, branch_id: uuid.UUID) -> ExecutionBranch:
        branch = self._require_branch(branch_id=branch_id, tenant_id=tenant_id)
        transition_branch(branch, ExecutionBranchState.FAILED)
        self._session.flush()
        return branch

    def _require_branch(self, *, branch_id: uuid.UUID, tenant_id: str) -> ExecutionBranch:
        branch = self._branches.get(branch_id)
        if branch is None or branch.tenant_id != tenant_id:
            raise ValueError("branch not found for tenant")
        return branch
