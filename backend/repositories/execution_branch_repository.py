from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.execution_branch import ExecutionBranch


class ExecutionBranchRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, branch: ExecutionBranch) -> ExecutionBranch:
        self._session.add(branch)
        self._session.flush()
        self._session.refresh(branch)
        return branch

    def get(self, branch_id: uuid.UUID) -> ExecutionBranch | None:
        return self._session.get(ExecutionBranch, branch_id)

    def list_for_mission(self, mission_id: uuid.UUID) -> list[ExecutionBranch]:
        stmt = select(ExecutionBranch).where(ExecutionBranch.mission_id == mission_id)
        return list(self._session.scalars(stmt))
