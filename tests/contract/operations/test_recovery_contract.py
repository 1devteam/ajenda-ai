from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.operations import router
from backend.app.dependencies.db import get_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.services.runtime_maintainer import RecoverySummary


class _RecoveryOpsService:
    def trigger_recovery(self) -> RecoverySummary:
        return RecoverySummary(
            expired_lease_count=2,
            requeued_task_count=1,
