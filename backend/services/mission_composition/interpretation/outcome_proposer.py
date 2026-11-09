"""Constrained model-assisted canonical outcome proposals.

The proposer is advisory: it cannot introduce vocabulary, actions, credentials,
or execution authority.  The interpreter remains the authority boundary.
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.services.mission_composition.contracts import CANONICAL_OUTCOMES


class OutcomeClauseProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clause_id: str = Field(min_length=1, max_length=80)
    outcomes: tuple[str, ...] = Field(min_length=1, max_length=8)


class OutcomeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clauses: tuple[OutcomeClauseProposal, ...] = ()


class CanonicalOutcomeProposer(Protocol):
    def propose(self, *, instruction: str, clauses: tuple[dict[str, str], ...]) -> OutcomeProposal: ...


class OutcomeProposalValidationError(ValueError):
    pass


def validate_outcome_proposal(proposal: OutcomeProposal, *, allowed_clause_ids: set[str]) -> OutcomeProposal:
    seen: set[str] = set()
    for clause in proposal.clauses:
        if clause.clause_id not in allowed_clause_ids:
            raise OutcomeProposalValidationError("outcome proposal referenced an unknown clause")
        if clause.clause_id in seen:
            raise OutcomeProposalValidationError("outcome proposal mapped a clause more than once")
        seen.add(clause.clause_id)
        if any(outcome not in CANONICAL_OUTCOMES for outcome in clause.outcomes):
            raise OutcomeProposalValidationError("outcome proposal contained a non-canonical outcome")
    return proposal


class ModelCanonicalOutcomeProposer:
    """Strict JSON adapter over an injected model generator."""

    def __init__(self, *, generator: object) -> None:
        self._generator = generator

    def propose(self, *, instruction: str, clauses: tuple[dict[str, str], ...]) -> OutcomeProposal:
        from backend.services.llm.contracts import LlmGenerateRequest

        generated = self._generator.generate(  # type: ignore[attr-defined]
            LlmGenerateRequest(
                system_prompt=(
                    "Return exactly one JSON object with clauses [{clause_id,outcomes}]. "
                    "Choose outcomes only from: " + ", ".join(sorted(CANONICAL_OUTCOMES)) + ". "
                    "Do not propose sends, writes, credentials, or authority."
                ),
                user_prompt=json.dumps({"instruction": instruction, "unmatched_clauses": clauses}, sort_keys=True),
                temperature=0.0,
                max_tokens=1000,
            )
        )
        if not bool(getattr(generated, "used_llm", False)):
            raise OutcomeProposalValidationError("outcome proposer requires a configured model")
        try:
            payload = json.loads(str(getattr(generated, "text", "")))
        except json.JSONDecodeError as exc:
            raise OutcomeProposalValidationError("outcome proposer returned invalid JSON") from exc
        return OutcomeProposal.model_validate(payload)
