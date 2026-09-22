"""Mission intake prompt quality gate — deny vague or senseless missions at intake."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

MISSION_INTAKE_QUALITY_SCHEMA_VERSION = 2

_COMPOSITION_CLARIFICATION_MARKERS = (
    "i cannot compose this mission reliably",
    "restat(e|ing) the complete mission",
    "the revised mission still does not include",
)


def contains_composition_clarification(value: Any) -> bool:
    """Return True when persisted UI context is itself a planner clarification.

    A clarification is not a mission objective. It must never be accepted as a
    direct mission instruction or allowed to reach runtime queue admission.
    """

    if isinstance(value, str):
        lowered = value.lower()
        return any(re.search(marker, lowered) for marker in _COMPOSITION_CLARIFICATION_MARKERS)
    if isinstance(value, dict):
        return any(contains_composition_clarification(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_composition_clarification(item) for item in value)
    return False


MissionIntakeQualitySeverity = Literal["required"]

_OBJECTIVE_MIN_CHARS = 24
_SUCCESS_CRITERION_MIN_CHARS = 20
_OBJECTIVE_MIN_CONTENT_WORDS = 4
_EVIDENCE_MIN_CHARS = 8

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "to",
        "for",
        "of",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "into",
        "about",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "my",
        "our",
        "your",
        "their",
        "me",
        "us",
        "you",
        "they",
        "it",
        "we",
        "i",
        "do",
        "does",
        "did",
        "doing",
        "done",
        "have",
        "has",
        "had",
        "having",
        "will",
        "would",
        "should",
        "could",
        "can",
        "may",
        "might",
        "must",
        "need",
        "needs",
        "needed",
        "want",
        "wants",
        "wanted",
        "just",
        "some",
        "any",
        "all",
        "more",
        "most",
        "very",
        "really",
        "please",
        "help",
        "make",
        "get",
        "go",
        "thing",
        "things",
        "stuff",
        "something",
        "anything",
        "everything",
        "work",
        "working",
        "better",
        "good",
        "nice",
        "great",
        "best",
    }
)

_OUTCOME_VERBS = frozenset(
    {
        "analyze",
        "analyse",
        "audit",
        "automate",
        "classify",
        "compare",
        "complete",
        "consolidate",
        "detect",
        "draft",
        "eliminate",
        "enrich",
        "extract",
        "find",
        "follow",
        "identify",
        "improve",
        "increase",
        "investigate",
        "map",
        "monitor",
        "notify",
        "organize",
        "organise",
        "plan",
        "prepare",
        "prioritize",
        "prioritise",
        "qualify",
        "reconcile",
        "recommend",
        "recover",
        "reduce",
        "research",
        "review",
        "route",
        "score",
        "summarize",
        "summarise",
        "surface",
        "sync",
        "track",
        "triage",
        "update",
        "validate",
        "verify",
    }
)

_MEASURABLE_MARKERS = frozenset(
    {
        "%",
        "all",
        "at least",
        "before",
        "complete",
        "completed",
        "confirmed",
        "count",
        "delivered",
        "documented",
        "each",
        "every",
        "listed",
        "minimum",
        "maximum",
        "no more than",
        "none remaining",
        "number",
        "percent",
        "rate",
        "ratio",
        "recorded",
        "sent",
        "summarized",
        "summarised",
        "threshold",
        "updated",
        "verified",
        "within",
        "zero",
    }
)

_VAGUE_CRITERION_PHRASES = frozenset(
    {
        "be better",
        "be successful",
        "do better",
        "do good",
        "do well",
        "finish",
        "get better",
        "get done",
        "go well",
        "improve things",
        "it works",
        "make it work",
        "mission complete",
        "mission success",
        "mission accomplished",
        "no issues",
        "looks good",
        "make money",
        "success",
        "successful",
        "works",
    }
)

_SCOPE_SIGNAL_MARKERS = frozenset(
    {
        "accounts",
        "across",
        "audience",
        "campaign",
        "city",
        "clients",
        "companies",
        "contacts",
        "customers",
        "days",
        "each",
        "emails",
        "every",
        "for ",
        "in ",
        "inbox",
        "leads",
        "market",
        "month",
        "opportunities",
        "per ",
        "pipeline",
        "prospects",
        "quarter",
        "records",
        "region",
        "segment",
        "territory",
        "week",
        "within",
    }
)

_VAGUE_SCOPE_LIMIT_PHRASES = frozenset(
    {
        "anywhere",
        "everywhere",
        "no limits",
        "no scope",
        "unlimited",
        "whatever",
    }
)

_PLACEHOLDER_ALLOWED_ACTIONS = frozenset(
    {
        "anything",
        "do anything",
        "everything",
        "whatever",
    }
)

_PLACEHOLDER_OBJECTIVES = frozenset(
    {
        "asdf",
        "bar",
        "be better",
        "do it",
        "do something",
        "do stuff",
        "do things",
        "fix things",
        "foo",
        "get better",
        "hello",
        "help me",
        "hi",
        "idk",
        "improve things",
        "just do it",
        "make it work",
        "make money",
        "mission",
        "run mission",
        "something",
        "test",
        "testing",
        "tbd",
        "todo",
        "whatever",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'-]*", re.IGNORECASE)


class MissionIntakeQualityViolation(BaseModel):
    """One intake-quality denial with a stable machine code."""

    model_config = ConfigDict(extra="forbid")

    field: str
    code: str
    reason: str
    severity: MissionIntakeQualitySeverity = "required"


class MissionIntakeQualityDeniedError(ValueError):
    """Raised when mission intake text fails the prompt quality gate."""

    def __init__(self, violations: list[MissionIntakeQualityViolation]) -> None:
        self.violations = violations
        message = violations[0].reason if violations else "mission intake quality denied"
        super().__init__(message)

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": "MISSION_INTAKE_QUALITY_DENIED",
            "message": "Mission intake failed prompt quality gate",
            "schema_version": MISSION_INTAKE_QUALITY_SCHEMA_VERSION,
            "violations": [item.model_dump() for item in self.violations],
        }


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def _content_words(text: str) -> list[str]:
    tokens = [token.lower() for token in _TOKEN_RE.findall(text)]
    return [token for token in tokens if token not in _STOPWORDS and len(token) > 1]


def _contains_outcome_signal(text: str) -> bool:
    lowered = text.lower()
    if any(char.isdigit() for char in text):
        return True
    words = _content_words(text)
    if any(word in _OUTCOME_VERBS for word in words):
        return True
    if any(marker in lowered for marker in _MEASURABLE_MARKERS):
        return True
    return False


def _is_measurable_text(text: str) -> bool:
    lowered = text.lower()
    if any(char.isdigit() for char in text):
        return True
    if any(marker in lowered for marker in _MEASURABLE_MARKERS):
        return True
    words = _content_words(text)
    return any(word in _OUTCOME_VERBS for word in words) and len(words) >= 3


def _is_placeholder_objective(text: str) -> bool:
    normalized = _normalize_text(text).lower().rstrip(".!?")
    if normalized in _PLACEHOLDER_OBJECTIVES:
        return True
    if len(normalized) <= 12 and normalized in _STOPWORDS:
        return True
    if normalized.startswith("test ") and len(normalized) < 40:
        return True
    return False


def _is_interrogative_only(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized.endswith("?"):
        return False
    return not _contains_outcome_signal(normalized)


def _is_repeated_character_spam(text: str) -> bool:
    compact = re.sub(r"\s+", "", text.lower())
    if len(compact) < 8:
        return False
    for char in set(compact):
        if compact.count(char) / len(compact) > 0.4:
            return True
    return False


def _has_scope_signal(text: str) -> bool:
    lowered = text.lower()
    # A concrete HTTPS URL is the complete scope for a governed web-page
    # observation.  It must satisfy intake quality without being forced into
    # a market/location vocabulary intended for prospect research.
    if re.search(r"\bhttps?://[^\s<>()]+", lowered):
        return True
    if any(char.isdigit() for char in text):
        return True
    return any(marker in lowered for marker in _SCOPE_SIGNAL_MARKERS)


def _is_vague_free_text(text: str) -> bool:
    normalized = _normalize_text(text).lower()
    if normalized in _VAGUE_CRITERION_PHRASES:
        return True
    if normalized in _PLACEHOLDER_OBJECTIVES:
        return True
    return len(_content_words(text)) < 3


def validate_mission_intake_prompt(
    *,
    objective: str,
    success_criteria: list[dict[str, Any]],
    constraints: list[dict[str, Any]] | None = None,
    scope_limits: list[str] | None = None,
    allowed_actions: list[str] | None = None,
    operator_notes: str | None = None,
    allow_legacy_v1: bool = False,
) -> None:
    """Fail closed when mission prompt text is too vague to plan or measure."""

    if allow_legacy_v1:
        return

    violations: list[MissionIntakeQualityViolation] = []
    normalized_objective = _normalize_text(objective)

    if _is_placeholder_objective(normalized_objective):
        violations.append(
            MissionIntakeQualityViolation(
                field="objective",
                code="objective_placeholder",
                reason="Objective reads like a placeholder or test prompt, not a concrete executable objective.",
            )
        )
    elif len(normalized_objective) < _OBJECTIVE_MIN_CHARS:
        violations.append(
            MissionIntakeQualityViolation(
                field="objective",
                code="objective_too_short",
                reason=(
                    f"Objective must be at least {_OBJECTIVE_MIN_CHARS} characters and describe a concrete outcome."
                ),
            )
        )
    elif _is_interrogative_only(normalized_objective):
        violations.append(
            MissionIntakeQualityViolation(
                field="objective",
                code="objective_interrogative_only",
                reason="Objective must state what should be accomplished, not only ask an open question.",
            )
        )
    elif len(_content_words(normalized_objective)) < _OBJECTIVE_MIN_CONTENT_WORDS:
        violations.append(
            MissionIntakeQualityViolation(
                field="objective",
                code="objective_too_few_content_words",
                reason="Objective must include enough specific nouns and verbs to describe the desired outcome.",
            )
        )
    elif _is_repeated_character_spam(normalized_objective):
        violations.append(
            MissionIntakeQualityViolation(
                field="objective",
                code="objective_repeated_character_spam",
                reason="Objective looks like keyboard noise or filler characters, not a concrete executable objective.",
            )
        )
    elif not _has_scope_signal(normalized_objective):
        violations.append(
            MissionIntakeQualityViolation(
                field="objective",
                code="objective_lacks_scope_signal",
                reason=(
                    "Objective must name who or what it targets — for example three leads, a market, a segment, "
                    "or a time window."
                ),
            )
        )
    elif not _contains_outcome_signal(normalized_objective):
        violations.append(
            MissionIntakeQualityViolation(
                field="objective",
                code="objective_no_outcome_signal",
                reason="Objective must describe an actionable outcome (for example: research, qualify, recover, draft, or verify).",
            )
        )

    normalized_objective_lower = normalized_objective.lower()
    measurable_criteria = 0
    seen_criteria: set[str] = set()

    for index, raw_criterion in enumerate(success_criteria):
        if not isinstance(raw_criterion, dict):
            violations.append(
                MissionIntakeQualityViolation(
                    field=f"success_criteria[{index}]",
                    code="success_criterion_invalid",
                    reason="Each success criterion must be an object with a description.",
                )
            )
            continue

        description = raw_criterion.get("description")
        if not isinstance(description, str):
            violations.append(
                MissionIntakeQualityViolation(
                    field=f"success_criteria[{index}].description",
                    code="success_criterion_missing_description",
                    reason="Each success criterion requires a description.",
                )
            )
            continue

        normalized_description = _normalize_text(description)
        field_name = f"success_criteria[{index}].description"

        lowered_description = normalized_description.lower()
        if lowered_description in _VAGUE_CRITERION_PHRASES:
            violations.append(
                MissionIntakeQualityViolation(
                    field=field_name,
                    code="success_criterion_too_vague",
                    reason="Success criterion is too vague to verify completion.",
                )
            )
            continue

        if len(normalized_description) < _SUCCESS_CRITERION_MIN_CHARS:
            violations.append(
                MissionIntakeQualityViolation(
                    field=field_name,
                    code="success_criterion_too_short",
                    reason=(
                        f"Success criterion must be at least {_SUCCESS_CRITERION_MIN_CHARS} characters and observable."
                    ),
                )
            )
            continue

        if lowered_description == normalized_objective_lower:
            violations.append(
                MissionIntakeQualityViolation(
                    field=field_name,
                    code="success_criterion_duplicate_objective",
                    reason="Success criterion must add measurable detail beyond repeating the objective.",
                )
            )
            continue

        if lowered_description in seen_criteria:
            violations.append(
                MissionIntakeQualityViolation(
                    field=field_name,
                    code="success_criterion_duplicate",
                    reason="Each success criterion must be distinct.",
                )
            )
            continue
        seen_criteria.add(lowered_description)

        evidence = raw_criterion.get("evidence")
        substantive_evidence = False
        if isinstance(evidence, list):
            substantive_evidence = any(
                isinstance(item, str) and len(item.strip()) >= _EVIDENCE_MIN_CHARS for item in evidence
            )

        if _is_measurable_text(normalized_description) or substantive_evidence:
            measurable_criteria += 1
        else:
            violations.append(
                MissionIntakeQualityViolation(
                    field=field_name,
                    code="success_criterion_not_measurable",
                    reason=(
                        "Success criterion must be measurable or include concrete evidence expectations "
                        "(counts, thresholds, deliverables, or named artifacts)."
                    ),
                )
            )

    if not violations and measurable_criteria == 0:
        violations.append(
            MissionIntakeQualityViolation(
                field="success_criteria",
                code="success_criteria_not_measurable",
                reason="At least one success criterion must be measurable or backed by evidence expectations.",
            )
        )

    for index, raw_constraint in enumerate(constraints or []):
        if not isinstance(raw_constraint, dict):
            continue
        description = raw_constraint.get("description")
        if not isinstance(description, str):
            continue
        normalized_description = _normalize_text(description)
        if _is_vague_free_text(normalized_description):
            violations.append(
                MissionIntakeQualityViolation(
                    field=f"constraints[{index}].description",
                    code="constraint_too_vague",
                    reason="Constraint descriptions must be specific enough to govern planning and execution.",
                )
            )

    for index, raw_scope_limit in enumerate(scope_limits or []):
        if not isinstance(raw_scope_limit, str):
            continue
        normalized_scope = _normalize_text(raw_scope_limit).lower()
        if normalized_scope in _VAGUE_SCOPE_LIMIT_PHRASES or _is_vague_free_text(raw_scope_limit):
            violations.append(
                MissionIntakeQualityViolation(
                    field=f"scope_limits[{index}]",
                    code="scope_limit_too_vague",
                    reason="Scope limits must bound the mission with concrete boundaries such as region, segment, or timeframe.",
                )
            )

    for index, raw_action in enumerate(allowed_actions or []):
        if not isinstance(raw_action, str):
            continue
        normalized_action = _normalize_text(raw_action).lower()
        if normalized_action in _PLACEHOLDER_ALLOWED_ACTIONS:
            violations.append(
                MissionIntakeQualityViolation(
                    field=f"allowed_actions[{index}]",
                    code="allowed_action_placeholder",
                    reason="Allowed actions must name concrete abilities such as web.search or gtm.email_draft.",
                )
            )

    if operator_notes is not None and _is_vague_free_text(operator_notes):
        violations.append(
            MissionIntakeQualityViolation(
                field="operator_notes",
                code="operator_notes_too_vague",
                reason="Operator notes must add concrete guidance, not placeholder text.",
            )
        )

    if violations:
        raise MissionIntakeQualityDeniedError(violations)
