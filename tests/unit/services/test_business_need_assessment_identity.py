"""Business assessment rejects goals outside the originating need identity."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.services.business_understanding.reasoning import (
    BusinessNeedReasoningService,
    NeedAssessmentRequest,
)
from backend.services.ontology.commercial_state import Goal


@pytest.mark.parametrize("mismatch", ["subject", "objective"])
def test_goal_identity_is_owned_by_the_originating_need(mismatch: str) -> None:
    subject = {"schema_version": 1, "object_type": "organization", "object_id": "customer-1"}
    need = SimpleNamespace(
        subject_references=[subject],
        objective_reference={"objective_key": "increase_conversion"},
        observation_references=[],
    )
    repository = MagicMock()
    repository.get_need_revision_for_tenant.return_value = need
    goal = Goal(
        goal_id="conversion",
        objective_key="other_objective" if mismatch == "objective" else "increase_conversion",
        name="Increase conversion",
        subject_refs=[] if mismatch == "subject" else [subject],
    )
    service = BusinessNeedReasoningService(repository)
    with pytest.raises(ValueError, match=f"goal {mismatch}s? must match"):
        service.assess(
            tenant_id="tenant-a",
            need_id="need-1",
            revision=1,
            request=NeedAssessmentRequest(goal=goal),
            producer="unit-test",
        )
    repository.add_assessment.assert_not_called()
