"""Local-LLM mission interpreter and deterministic meaning guard."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Protocol

from backend.app.config import Settings, get_settings
from backend.services.mission_composition.contracts import (
    Clarification,
    Contradiction,
    InterpretationEvidence,
    InterpretedClause,
    MissionIntent,
    SemanticUnit,
    SendPolicy,
    StructuredPolicy,
    SuccessCriterion,
    TargetEntity,
    TimingConstraint,
)
from backend.services.mission_composition.interpretation.llm_client import (
    MissionInterpretationRequest,
    MissionInterpreterClient,
    MissionInterpreterTransportError,
    OpenAiCompatibleMissionInterpreterClient,
)
from backend.services.mission_composition.interpretation.prompts import SYSTEM_PROMPT, build_user_prompt
from backend.services.mission_composition.interpretation.schema import (
    GroundedOutcome,
    GroundedPolicy,
    InterpretationSegment,
    LlmMissionInterpretation,
)
from backend.services.mission_composition.readiness import evaluate_interpretation_readiness

_WS_RE = re.compile(r"\s+")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
_INTEGER_RE = re.compile(r"\b\d+\b")
_TEXT_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}
_NUMBER_WORD_RE = re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", re.IGNORECASE)
_NUMBER_TOKEN_PATTERN = r"(?:\d+|" + "|".join(_NUMBER_WORDS) + r")"
_REQUESTED_QUANTITY_RE = re.compile(
    r"\b(?:find|fnd|research|rsearch|identify|discover|locate|list|return|get|select|qualify|enrich|"
    r"draft|prepare|send|email|contact|need|want)\s+(?:me\s+)?(?:the\s+)?(?:top\s+)?"
    rf"(?P<quantity>{_NUMBER_TOKEN_PATTERN})\b",
    re.IGNORECASE,
)
_NON_COUNT_UNIT_RE = re.compile(
    r"^\s*[- ]?\s*(?:%|percent|km|kilometers?|mi|miles?|radius|seconds?|minutes?|hours?|days?|weeks?|"
    r"months?|years?|dollars?|usd|pages?|words?|characters?|paragraphs?)\b",
    re.IGNORECASE,
)


class MissionInterpreter(Protocol):
    def interpret(
        self,
        instruction: str,
        *,
        profile_context: dict[str, Any] | None = None,
    ) -> MissionIntent: ...


class MissionInterpreterOutputError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LlmMissionInterpreter:
    """Normalize human language into an untrusted ``MissionIntent`` candidate.

    The model owns language interpretation only. Grounding, schema acceptance,
    interpretation readiness, and every downstream Ajenda decision remain
    deterministic backend responsibilities.
    """

    def __init__(self, *, client: MissionInterpreterClient) -> None:
        self._client = client

    def interpret(
        self,
        instruction: str,
        *,
        profile_context: dict[str, Any] | None = None,
    ) -> MissionIntent:
        if not instruction or not instruction.strip():
            raise MissionInterpreterOutputError(code="INSTRUCTION_REQUIRED", message="instruction is required")
        if len(instruction) > 8000:
            raise MissionInterpreterOutputError(
                code="INSTRUCTION_TOO_LONG",
                message="instruction exceeds the 8000 character limit",
            )

        candidate = self._client.interpret(
            MissionInterpretationRequest(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(instruction=instruction, profile_context=profile_context),
            )
        )
        # Small local models often invent soft target fields (industry labels, wrong
        # type tokens). Strip those before fail-closed grounding — never invent facts.
        candidate = _sanitize_candidate_against_instruction(
            instruction=instruction,
            candidate=candidate,
            profile_context=profile_context or {},
        )
        _validate_candidate_grounding(
            instruction=instruction,
            candidate=candidate,
            profile_context=profile_context or {},
        )
        return _to_mission_intent(instruction=instruction, candidate=candidate)


def build_mission_interpreter(*, settings: Settings | None = None) -> MissionInterpreter:
    resolved = settings or get_settings()
    return LlmMissionInterpreter(client=OpenAiCompatibleMissionInterpreterClient(settings=resolved))


def _normalize_source(value: str) -> str:
    return _WS_RE.sub(" ", value).strip().casefold()


def _source_is_grounded(source_text: str, source: str) -> bool:
    needle = _normalize_source(source_text)
    return bool(needle) and needle in _normalize_source(source)


def _profile_source(profile_context: dict[str, Any]) -> str:
    values: list[str] = []
    for value in profile_context.values():
        if isinstance(value, str) and value.strip():
            values.append(value)
        elif isinstance(value, dict):
            values.extend(str(item) for item in value.values() if isinstance(item, str) and item.strip())
    return "\n".join(values)


def _sanitize_candidate_against_instruction(
    *,
    instruction: str,
    candidate: LlmMissionInterpretation,
    profile_context: dict[str, Any],
) -> LlmMissionInterpretation:
    """Repair broken spans from small models without inventing mission facts.

    - Drop target/segment/outcome spans that are not substrings of the instruction.
    - Reset material policies whose source_text is ungrounded unless the
      instruction itself contains matching policy language.
    - Replace unusable interpreted_instruction with the raw instruction.
    - Ensure coverage by keeping only grounded segments + exact raw instruction.
    """

    raw = instruction.strip()
    lowered = raw.casefold()
    profile_text = _profile_source(profile_context)
    updates_top: dict[str, Any] = {}

    # --- interpreted_instruction: must be grounded and not a bare outcome id ---
    interpreted = (candidate.interpreted_instruction or "").strip()
    if (
        not interpreted
        or not _source_is_grounded(interpreted, instruction)
        or interpreted.casefold().replace(" ", "_")
        in {
            "research_prospects",
            "qualify_prospects",
            "enrich_contacts",
            "prepare_outreach",
            "send_outreach",
            "update_crm",
            "publish_content",
            "read_calendar",
            "read_email",
            "read_crm",
            "query_salesforce",
        }
    ):
        updates_top["interpreted_instruction"] = raw[:8000]

    # --- targets ---
    cleaned_targets = []
    for target in candidate.target_entities:
        source = profile_text if target.source == "profile_context" else instruction
        if not _source_is_grounded(target.source_text, source):
            continue
        cleaned_targets.append(target)
    updates_top["target_entities"] = cleaned_targets

    # --- quantity source ---
    qty = candidate.requested_quantity
    qty_source = candidate.quantity_source_text
    instruction_numbers = _number_facts(instruction)
    if qty is not None:
        if qty not in instruction_numbers:
            # Drop invented counts; do not invent a different number.
            updates_top["requested_quantity"] = None
            updates_top["quantity_source_text"] = None
        elif not qty_source or not _source_is_grounded(qty_source, instruction):
            # Prefer a short span that contains the number, else full instruction.
            qty_str = str(qty)
            filled = raw
            for token in (qty_str, "five", "ten", "three", "at least five", "at least 5"):
                if token in lowered:
                    # use exact casing slice when possible
                    idx = lowered.find(token)
                    if idx >= 0:
                        filled = raw[idx : idx + len(token)]
                        break
            updates_top["quantity_source_text"] = filled[:1000]
    elif qty_source and not _source_is_grounded(qty_source, instruction):
        updates_top["quantity_source_text"] = None

    # --- policies: never keep material mode with ungrounded source ---
    forbid_markers = (
        "do not send",
        "don't send",
        "dont send",
        "never send",
        "without sending",
        "draft only",
        "do not email",
        "don't email",
    )
    has_forbid_language = any(marker in lowered for marker in forbid_markers)

    def _clean_policy(policy: GroundedPolicy) -> GroundedPolicy:
        if policy.mode == "unknown":
            return policy.model_copy(update={"source_text": None}) if policy.source_text else policy
        source_text = (policy.source_text or "").strip()
        if source_text and _source_is_grounded(source_text, instruction):
            return policy
        # Material mode without grounded source.
        if policy.mode == "forbid" and has_forbid_language:
            # Attach a grounded forbid span from the instruction.
            filled = raw
            for marker in forbid_markers:
                idx = lowered.find(marker)
                if idx >= 0:
                    filled = raw[idx : idx + len(marker)]
                    break
            return policy.model_copy(update={"source_text": filled[:1000], "condition": "none"})
        # Invented allow/forbid/conditional without instruction support → unknown.
        return GroundedPolicy(mode="unknown", condition="none", source_text=None)

    updates_top["send_policy"] = _clean_policy(candidate.send_policy)
    updates_top["contact_policy"] = _clean_policy(candidate.contact_policy)
    updates_top["publish_policy"] = _clean_policy(candidate.publish_policy)
    updates_top["write_policy"] = _clean_policy(candidate.write_policy)

    # --- segments: drop ungrounded paraphrases; ensure raw instruction coverage ---
    grounded_segments: list[InterpretationSegment] = []
    for item in candidate.segments:
        if _source_is_grounded(item.source_text, instruction):
            grounded_segments.append(item)
    if raw:
        if not any(_normalize_source(item.source_text) == _normalize_source(raw) for item in grounded_segments):
            grounded_segments.append(
                InterpretationSegment(
                    source_text=raw[:2000],
                    normalized_text=raw[:2000],
                    accounted=True,
                    material=True,
                )
            )
    updates_top["segments"] = grounded_segments or [
        InterpretationSegment(
            source_text=raw[:2000] or "instruction",
            normalized_text=raw[:2000] or "instruction",
            accounted=True,
            material=True,
        )
    ]

    # --- outcomes: keep grounded sources; re-ground only when instruction language supports it ---
    outcome_markers: dict[str, tuple[str, ...]] = {
        "research_prospects": (
            "research",
            "find ",
            "discover",
            "locate",
            "businesses",
            "companies",
            "prospect",
            "roofers",
            "contractors",
        ),
        "enrich_contacts": (
            "contact info",
            "contact information",
            "phone",
            "email address",
            "return the contact",
            "contacts",
        ),
        "prepare_outreach": ("draft", "do not send", "don't send", "prepare", "without sending"),
        "qualify_prospects": ("qualify", "score", "rank", "strongest"),
        "send_outreach": ("send email", "send outreach", "send them"),
        "publish_content": ("publish", "post to", "social"),
    }

    def _marker_span(markers: tuple[str, ...]) -> str:
        for marker in markers:
            idx = lowered.find(marker)
            if idx >= 0:
                end = min(len(raw), idx + max(len(marker), 28))
                return raw[idx:end]
        return raw

    cleaned_outcomes: list[GroundedOutcome] = []
    seen_outcomes: set[str] = set()
    for item in candidate.requested_outcomes:
        markers = outcome_markers.get(item.outcome, ())
        if _source_is_grounded(item.source_text, instruction):
            if item.outcome in seen_outcomes:
                continue
            seen_outcomes.add(item.outcome)
            cleaned_outcomes.append(item)
            continue
        # Ungrounded source: keep only if instruction language supports this outcome.
        if markers and any(marker in lowered for marker in markers):
            if item.outcome in seen_outcomes:
                continue
            seen_outcomes.add(item.outcome)
            cleaned_outcomes.append(
                item.model_copy(update={"source_text": _marker_span(markers)[:1000]})
            )

    def _ensure_outcome(outcome_id: str, *, markers: tuple[str, ...]) -> None:
        if outcome_id in seen_outcomes:
            return
        if not any(marker in lowered for marker in markers):
            return
        cleaned_outcomes.append(
            GroundedOutcome(outcome=outcome_id, source_text=_marker_span(markers)[:1000])  # type: ignore[arg-type]
        )
        seen_outcomes.add(outcome_id)

    _ensure_outcome("research_prospects", markers=outcome_markers["research_prospects"])
    _ensure_outcome("enrich_contacts", markers=outcome_markers["enrich_contacts"])
    send_policy = updates_top.get("send_policy", candidate.send_policy)
    if getattr(send_policy, "mode", None) == "forbid":
        _ensure_outcome("prepare_outreach", markers=outcome_markers["prepare_outreach"])

    updates_top["requested_outcomes"] = cleaned_outcomes

    # success criteria with ungrounded source → drop or re-source description from instruction
    fixed_criteria = []
    for item in candidate.success_criteria:
        if _source_is_grounded(item.source_text, instruction):
            fixed_criteria.append(item)
            continue
        if item.description and _source_is_grounded(item.description, instruction):
            fixed_criteria.append(item.model_copy(update={"source_text": item.description[:1000]}))
    updates_top["success_criteria"] = fixed_criteria

    return candidate.model_copy(update=updates_top)


def _validate_candidate_grounding(
    *,
    instruction: str,
    candidate: LlmMissionInterpretation,
    profile_context: dict[str, Any],
) -> None:
    sources: list[tuple[str, str]] = []
    for outcome in [*candidate.requested_outcomes, *candidate.forbidden_outcomes]:
        sources.append((f"outcome:{outcome.outcome}", outcome.source_text))
    sources.extend(("unsupported_outcome", item.source_text) for item in candidate.unsupported_outcomes)
    sources.extend(
        (f"context_requirement:{item.requirement}", item.source_text) for item in candidate.context_requirements
    )
    if candidate.requested_quantity is not None and candidate.quantity_source_text:
        sources.append(("requested_quantity", candidate.quantity_source_text))
        source_quantities = _number_facts(candidate.quantity_source_text)
        if candidate.requested_quantity not in source_quantities:
            raise MissionInterpreterOutputError(
                code="INTERPRETER_INVENTED_QUANTITY",
                message="structured interpretation introduced a quantity that was not provided",
            )
    for name, policy in (
        ("send_policy", candidate.send_policy),
        ("contact_policy", candidate.contact_policy),
        ("publish_policy", candidate.publish_policy),
        ("write_policy", candidate.write_policy),
    ):
        if policy.mode != "unknown" and policy.source_text:
            sources.append((name, policy.source_text))
    sources.extend(("timing_constraint", item.source_text) for item in candidate.timing_constraints)
    sources.extend(("constraint", item.source_text) for item in candidate.constraints)
    sources.extend(("success_criterion", item.source_text) for item in candidate.success_criteria)
    sources.extend(("segment", item.source_text) for item in candidate.segments)
    for contradiction in candidate.contradictions:
        sources.extend(
            (
                ("contradiction:first_span", contradiction.first_span),
                ("contradiction:second_span", contradiction.second_span),
            )
        )

    ungrounded = [name for name, source_text in sources if not _source_is_grounded(source_text, instruction)]
    profile_text = _profile_source(profile_context)
    for target in candidate.target_entities:
        source = profile_text if target.source == "profile_context" else instruction
        if not _source_is_grounded(target.source_text, source):
            ungrounded.append(f"target:{target.type}")
        for field_name in ("name", "industry", "location"):
            value = getattr(target, field_name)
            if value and not _target_text_is_source_correspondent(value, target.source_text):
                ungrounded.append(f"target:{field_name}")
        for field_name in ("domain", "url", "email"):
            value = getattr(target, field_name)
            if value and _normalize_source(value) not in _normalize_source(source):
                ungrounded.append(f"target:{field_name}")
        if target.radius_km is not None and not _radius_is_grounded(target.radius_km, target.source_text):
            ungrounded.append("target:radius_km")
    if ungrounded:
        raise MissionInterpreterOutputError(
            code="INTERPRETER_UNGROUNDED_OUTPUT",
            message=f"interpretation contains ungrounded fields: {', '.join(sorted(set(ungrounded)))}",
        )

    _validate_protected_facts(instruction=instruction, candidate=candidate)


def _validate_protected_facts(*, instruction: str, candidate: LlmMissionInterpretation) -> None:
    interpreted = candidate.interpreted_instruction
    raw_emails = {item.casefold() for item in _EMAIL_RE.findall(instruction)}
    interpreted_emails = {item.casefold() for item in _EMAIL_RE.findall(interpreted)}
    raw_urls = {item.casefold().rstrip(".,") for item in _URL_RE.findall(instruction)}
    interpreted_urls = {item.casefold().rstrip(".,") for item in _URL_RE.findall(interpreted)}
    raw_numbers = _number_facts(instruction)
    interpreted_numbers = _number_facts(interpreted)
    target_emails = {
        str(target.email).casefold()
        for target in candidate.target_entities
        if target.email and str(target.email).strip()
    }
    target_urls = {
        str(target.url).casefold().rstrip(".,")
        for target in candidate.target_entities
        if target.url and str(target.url).strip()
    }

    if not raw_emails.issubset(interpreted_emails) or not raw_emails.issubset(target_emails):
        raise MissionInterpreterOutputError(
            code="INTERPRETER_DROPPED_RECIPIENT",
            message="interpretation omitted a supplied email address from the reviewed wording or target schema",
        )
    if not interpreted_emails.issubset(raw_emails):
        raise MissionInterpreterOutputError(
            code="INTERPRETER_INVENTED_RECIPIENT",
            message="interpretation introduced an email address that was not provided",
        )
    if not raw_urls.issubset(interpreted_urls) or not raw_urls.issubset(target_urls):
        raise MissionInterpreterOutputError(
            code="INTERPRETER_DROPPED_URL",
            message="interpretation omitted a supplied URL from the reviewed wording or target schema",
        )
    if not interpreted_urls.issubset(raw_urls):
        raise MissionInterpreterOutputError(
            code="INTERPRETER_INVENTED_URL",
            message="interpretation introduced a URL that was not provided",
        )
    if not _counter_is_subset(raw_numbers, interpreted_numbers):
        raise MissionInterpreterOutputError(
            code="INTERPRETER_DROPPED_QUANTITY",
            message="interpretation omitted a supplied numeric fact from the reviewed wording",
        )
    if not _counter_is_subset(interpreted_numbers, raw_numbers):
        raise MissionInterpreterOutputError(
            code="INTERPRETER_INVENTED_QUANTITY",
            message="interpretation introduced a quantity that was not provided",
        )
    _validate_requested_quantity_binding(instruction=instruction, candidate=candidate)
    _validate_typed_numeric_fields(candidate)
    structured_numbers = _structured_number_facts(candidate)
    raw_number_values = set(raw_numbers)
    if not raw_number_values.issubset(structured_numbers):
        raise MissionInterpreterOutputError(
            code="INTERPRETER_DROPPED_QUANTITY",
            message="interpretation omitted a supplied numeric fact from the structured mission details",
        )
    if not structured_numbers.issubset(raw_number_values):
        raise MissionInterpreterOutputError(
            code="INTERPRETER_INVENTED_QUANTITY",
            message="structured interpretation introduced a numeric fact that was not provided",
        )


def _target_text_is_source_correspondent(value: str, source_text: str) -> bool:
    """Allow bounded spelling/inflection repair without accepting new target facts."""

    exact_value_tokens = [item.casefold() for item in _TEXT_TOKEN_RE.findall(value)]
    exact_source_tokens = [item.casefold() for item in _TEXT_TOKEN_RE.findall(source_text)]
    if _contains_token_sequence(exact_source_tokens, exact_value_tokens):
        return True
    value_tokens = [item for item in exact_value_tokens if not item.isdigit()]
    source_tokens = [item for item in exact_source_tokens if not item.isdigit()]
    if not value_tokens or not source_tokens:
        return False
    return all(any(_tokens_correspond(token, source_token) for source_token in source_tokens) for token in value_tokens)


def _contains_token_sequence(source: list[str], candidate: list[str]) -> bool:
    if not candidate or len(candidate) > len(source):
        return False
    width = len(candidate)
    return any(source[index : index + width] == candidate for index in range(len(source) - width + 1))


def _tokens_correspond(value: str, source: str) -> bool:
    if value == source:
        return True
    if len(value) < 4 or len(source) < 4:
        return False
    if _morphological_stems(value) & _morphological_stems(source):
        return True
    max_edits = 1 if max(len(value), len(source)) <= 7 else 2
    return _edit_distance_with_limit(value, source, max_edits) <= max_edits


def _morphological_stems(token: str) -> set[str]:
    stems = {token}
    if token.endswith("ies") and len(token) > 4:
        stems.add(f"{token[:-3]}y")
    for suffix in ("ing", "ers", "er", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            stems.add(token[: -len(suffix)])
    return stems


def _edit_distance_with_limit(left: str, right: str, limit: int) -> int:
    """Return Levenshtein distance, stopping when it cannot be within the limit."""

    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for row_index, left_char in enumerate(left, start=1):
        current = [row_index]
        for column_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column_index] + 1,
                    previous[column_index - 1] + (left_char != right_char),
                )
            )
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _validate_requested_quantity_binding(*, instruction: str, candidate: LlmMissionInterpretation) -> None:
    """Bind explicit action counts to requested_quantity, never an unrelated numeric field."""

    required = _requested_quantity_facts(instruction)
    if not required:
        return
    quantity_source = candidate.quantity_source_text or ""
    for value, source_span in required:
        source_overlaps = _source_is_grounded(quantity_source, source_span) or _source_is_grounded(
            source_span, quantity_source
        )
        if candidate.requested_quantity != value or not source_overlaps:
            raise MissionInterpreterOutputError(
                code="INTERPRETER_DROPPED_QUANTITY",
                message="an explicit action count was not represented by requested_quantity and its source span",
            )


def _requested_quantity_facts(instruction: str) -> list[tuple[int, str]]:
    facts: list[tuple[int, str]] = []
    for match in _REQUESTED_QUANTITY_RE.finditer(instruction):
        if _NON_COUNT_UNIT_RE.match(instruction[match.end("quantity") :]):
            continue
        values = _number_facts(match.group("quantity"))
        if len(values) == 1:
            facts.append((next(iter(values)), match.group(0)))
    return facts


def _validate_typed_numeric_fields(candidate: LlmMissionInterpretation) -> None:
    """Prevent a raw number from being moved into an unrelated structured field."""

    for target in candidate.target_entities:
        for value in (target.name, target.industry, target.location, target.domain, target.url, target.email):
            if value and not _counter_is_subset(_number_facts(value), _number_facts(target.source_text)):
                raise MissionInterpreterOutputError(
                    code="INTERPRETER_INVENTED_QUANTITY",
                    message="a target numeric fact does not match its cited source span",
                )
    for timing in candidate.timing_constraints:
        normalized = " ".join(value for value in (timing.start, timing.end, timing.label) if value)
        if not _counter_is_subset(_number_facts(normalized), _number_facts(timing.source_text)):
            raise MissionInterpreterOutputError(
                code="INTERPRETER_INVENTED_QUANTITY",
                message="a timing numeric fact does not match its cited source span",
            )
    for constraint_item in candidate.constraints:
        if not _counter_is_subset(_number_facts(constraint_item.text), _number_facts(constraint_item.source_text)):
            raise MissionInterpreterOutputError(
                code="INTERPRETER_INVENTED_QUANTITY",
                message="a constraint numeric fact does not match its cited source span",
            )
    for criterion in candidate.success_criteria:
        if not _counter_is_subset(_number_facts(criterion.description), _number_facts(criterion.source_text)):
            raise MissionInterpreterOutputError(
                code="INTERPRETER_INVENTED_QUANTITY",
                message="a success-criterion numeric fact does not match its cited source span",
            )


def _structured_number_facts(candidate: LlmMissionInterpretation) -> set[int]:
    values: set[int] = set()
    if candidate.requested_quantity is not None:
        values.add(candidate.requested_quantity)
    texts: list[str] = []
    for target in candidate.target_entities:
        texts.extend(
            value
            for value in (
                target.name,
                target.industry,
                target.location,
                target.domain,
                target.url,
                target.email,
            )
            if value
        )
        if target.radius_km is not None:
            texts.append(str(int(target.radius_km)) if target.radius_km.is_integer() else str(target.radius_km))
    for timing in candidate.timing_constraints:
        texts.extend(value for value in (timing.start, timing.end, timing.label) if value)
    texts.extend(item.text for item in candidate.constraints)
    texts.extend(item.description for item in candidate.success_criteria)
    for text in texts:
        values.update(_number_facts(text))
    return values


def _radius_is_grounded(radius_km: float, source_text: str) -> bool:
    if radius_km.is_integer():
        return int(radius_km) in _number_facts(source_text)
    return str(radius_km) in source_text


def _number_facts(value: str) -> Counter[int]:
    values = [int(item) for item in _INTEGER_RE.findall(value)]
    values.extend(_NUMBER_WORDS[item.casefold()] for item in _NUMBER_WORD_RE.findall(value))
    return Counter(values)


def _counter_is_subset(candidate: Counter[int], source: Counter[int]) -> bool:
    return all(count <= source.get(value, 0) for value, count in candidate.items())


def _policy(policy: GroundedPolicy, *, rule_id: str) -> SendPolicy:
    return SendPolicy(
        mode=policy.mode,
        condition=policy.condition,
        source="explicit" if policy.mode != "unknown" else "unresolved",
        confidence=policy.confidence if policy.mode != "unknown" else 0.0,
        rule_id=rule_id if policy.mode != "unknown" else None,
    )


def _structured_policy(policy: GroundedPolicy, *, rule_id: str) -> StructuredPolicy:
    return StructuredPolicy(
        mode=policy.mode,
        condition=policy.condition,
        source="explicit" if policy.mode != "unknown" else "unresolved",
        confidence=policy.confidence if policy.mode != "unknown" else 0.0,
        rule_id=rule_id if policy.mode != "unknown" else None,
    )


def _to_mission_intent(*, instruction: str, candidate: LlmMissionInterpretation) -> MissionIntent:
    evidence: list[InterpretationEvidence] = []
    for field_name, outcomes in (
        ("requested_outcomes", candidate.requested_outcomes),
        ("forbidden_outcomes", candidate.forbidden_outcomes),
    ):
        for index, outcome in enumerate(outcomes):
            evidence.append(
                InterpretationEvidence(
                    field_path=f"{field_name}[{index}]",
                    source="explicit",
                    source_text=outcome.source_text,
                    normalized_value=outcome.outcome,
                    confidence=outcome.confidence,
                    rule_id="local_llm.schema_outcome",
                    components_active=["local_llm", "json_schema", "meaning_guard"],
                )
            )
    for index, unsupported in enumerate(candidate.unsupported_outcomes):
        evidence.append(
            InterpretationEvidence(
                field_path=f"unsupported_outcomes[{index}]",
                source="explicit",
                source_text=unsupported.source_text,
                normalized_value=unsupported.text,
                confidence=unsupported.confidence,
                rule_id="local_llm.schema_unsupported_outcome",
                components_active=["local_llm", "json_schema", "meaning_guard"],
            )
        )
    if candidate.requested_quantity is not None:
        evidence.append(
            InterpretationEvidence(
                field_path="requested_quantity",
                source="explicit",
                source_text=candidate.quantity_source_text,
                normalized_value=str(candidate.requested_quantity),
                confidence=1.0,
                rule_id="local_llm.schema_quantity",
                components_active=["local_llm", "json_schema", "meaning_guard"],
            )
        )
    for name, policy in (
        ("send_policy", candidate.send_policy),
        ("contact_policy", candidate.contact_policy),
        ("publish_policy", candidate.publish_policy),
        ("write_policy", candidate.write_policy),
    ):
        if policy.mode != "unknown":
            evidence.append(
                InterpretationEvidence(
                    field_path=name,
                    source="explicit",
                    source_text=policy.source_text,
                    normalized_value=f"{policy.mode}:{policy.condition}",
                    confidence=policy.confidence,
                    rule_id=f"local_llm.schema_{name}",
                    components_active=["local_llm", "json_schema", "meaning_guard"],
                )
            )
    for index, target in enumerate(candidate.target_entities):
        values = [
            target.type,
            target.name,
            target.industry,
            target.location,
            target.domain,
            target.url,
            target.email,
            str(target.radius_km) if target.radius_km is not None else None,
        ]
        evidence.append(
            InterpretationEvidence(
                field_path=f"target_entities[{index}]",
                source="profile_context" if target.source == "profile_context" else "explicit",
                source_text=target.source_text,
                normalized_value=" | ".join(value for value in values if value),
                confidence=target.confidence,
                rule_id="local_llm.schema_target",
                components_active=["local_llm", "json_schema", "meaning_guard"],
            )
        )
    for index, timing in enumerate(candidate.timing_constraints):
        evidence.append(
            InterpretationEvidence(
                field_path=f"timing_constraints[{index}]",
                source="explicit",
                source_text=timing.source_text,
                normalized_value=" | ".join(
                    value for value in (timing.kind, timing.start, timing.end, timing.label) if value
                ),
                confidence=timing.confidence,
                rule_id="local_llm.schema_timing",
                components_active=["local_llm", "json_schema", "meaning_guard"],
            )
        )
    for index, constraint in enumerate(candidate.constraints):
        evidence.append(
            InterpretationEvidence(
                field_path=f"constraints[{index}]",
                source="explicit",
                source_text=constraint.source_text,
                normalized_value=constraint.text,
                confidence=constraint.confidence,
                rule_id="local_llm.schema_constraints",
                components_active=["local_llm", "json_schema", "meaning_guard"],
            )
        )
    for index, criterion in enumerate(candidate.success_criteria):
        evidence.append(
            InterpretationEvidence(
                field_path=f"success_criteria[{index}]",
                source="explicit",
                source_text=criterion.source_text,
                normalized_value=criterion.description,
                confidence=criterion.confidence,
                rule_id="local_llm.schema_success_criteria",
                components_active=["local_llm", "json_schema", "meaning_guard"],
            )
        )
    for index, requirement in enumerate(candidate.context_requirements):
        evidence.append(
            InterpretationEvidence(
                field_path=f"context_requirements[{index}]",
                source="explicit",
                source_text=requirement.source_text,
                normalized_value=requirement.requirement,
                confidence=requirement.confidence,
                rule_id="local_llm.schema_context_requirements",
                components_active=["local_llm", "json_schema", "meaning_guard"],
            )
        )

    interpreted_clauses = [
        InterpretedClause(
            clause_id=f"llm-segment-{index + 1}",
            text=item.source_text,
            status="recognized" if item.accounted else "unmatched",
            material=item.material,
            mapped_outcomes=list(item.mapped_outcomes),
            reason=item.reason,
        )
        for index, item in enumerate(candidate.segments)
    ]
    semantic_units = [
        SemanticUnit(
            unit_id=f"llm-unit-{index + 1}",
            kind=item.kind,
            text=item.source_text,
            accounted=item.accounted,
            mapped_outcomes=list(item.mapped_outcomes),
            risk=item.risk,
            reason=item.reason,
        )
        for index, item in enumerate(candidate.segments)
    ]
    unmatched_clauses = [item for item in interpreted_clauses if item.material and item.status == "unmatched"]
    unmatched_units = [
        unit
        for unit, segment in zip(semantic_units, candidate.segments, strict=True)
        if segment.material and not unit.accounted
    ]
    coverage = _segment_coverage(instruction=instruction, candidate=candidate)
    clarifications = [
        Clarification(field=item.field, question=item.question, reason=item.reason) for item in candidate.clarifications
    ]
    clarification_fields = {item.field for item in clarifications}
    for unsupported_item in candidate.unsupported_outcomes:
        field = "unsupported_outcomes"
        if field not in clarification_fields:
            clarifications.append(
                Clarification(
                    field=field,
                    question=(
                        f"Ajenda cannot map this requested result yet: '{unsupported_item.text}'. "
                        "Restate the complete mission without it or choose a supported result."
                    ),
                    reason="The interpreter identified a requested outcome outside Ajenda's governed catalog.",
                )
            )
            clarification_fields.add(field)
    for index, segment_item in enumerate(candidate.segments):
        if segment_item.material and not segment_item.accounted:
            field = f"unmatched_segment_{index + 1}"
            if field not in clarification_fields:
                clarifications.append(
                    Clarification(
                        field=field,
                        question=(
                            f"Clarify this part when you restate the complete mission: '{segment_item.source_text}'."
                        ),
                        reason=segment_item.reason or "The interpreter could not account for this material wording.",
                    )
                )
                clarification_fields.add(field)
    for contradiction in candidate.contradictions:
        if contradiction.field_path not in clarification_fields:
            clarifications.append(
                Clarification(
                    field=contradiction.field_path,
                    question=(
                        f"Choose one meaning for '{contradiction.first_span}' versus "
                        f"'{contradiction.second_span}', "
                        "then restate the complete mission."
                    ),
                    reason="The request contains conflicting values for the same mission detail.",
                )
            )
            clarification_fields.add(contradiction.field_path)
    if (
        "send_outreach" in [item.outcome for item in candidate.requested_outcomes]
        and candidate.send_policy.mode == "unknown"
        and "send_policy" not in clarification_fields
    ):
        clarifications.append(
            Clarification(
                field="send_policy",
                question=(
                    "State whether Ajenda may send the outreach or must prepare drafts only, "
                    "then restate the complete mission."
                ),
                reason="External delivery requires an explicit user instruction.",
            )
        )
        clarification_fields.add("send_policy")
    external_risk = any(
        item.outcome
        in {
            "send_outreach",
            "update_crm",
            "publish_content",
            "read_email",
            "read_crm",
            "query_salesforce",
        }
        for item in candidate.requested_outcomes
    )
    confidence_threshold = 0.85 if external_risk else 0.7
    minimum_confidence = min((item.confidence for item in evidence), default=1.0)
    if minimum_confidence < confidence_threshold and "low_confidence" not in clarification_fields:
        clarifications.append(
            Clarification(
                field="low_confidence",
                question="Restate the complete mission with clearer targets, outcomes, and limits.",
                reason=(
                    f"One or more interpreted details were below the {confidence_threshold:.2f} confidence threshold."
                ),
            )
        )
        clarification_fields.add("low_confidence")
    if not candidate.requested_outcomes and not candidate.unsupported_outcomes and not clarifications:
        clarifications.append(
            Clarification(
                field="requested_outcomes",
                question="Restate the complete mission with the outcome Ajenda should accomplish.",
                reason="The interpreter could not identify a supported mission outcome.",
            )
        )

    intent = MissionIntent(
        raw_instruction=instruction,
        normalized_instruction=candidate.interpreted_instruction,
        objective=candidate.interpreted_instruction,
        requested_outcomes=[item.outcome for item in candidate.requested_outcomes],
        unsupported_outcomes=[item.text for item in candidate.unsupported_outcomes],
        requested_quantity=candidate.requested_quantity,
        quantity_provenance="explicit" if candidate.requested_quantity is not None else None,
        send_policy=_policy(candidate.send_policy, rule_id="local_llm.send_policy"),
        contact_policy=_structured_policy(candidate.contact_policy, rule_id="local_llm.contact_policy"),
        publish_policy=_structured_policy(candidate.publish_policy, rule_id="local_llm.publish_policy"),
        write_policy=_structured_policy(candidate.write_policy, rule_id="local_llm.write_policy"),
        target_entities=[
            TargetEntity(
                type=item.type,
                industry=item.industry,
                location=item.location,
                name=item.name,
                radius_km=item.radius_km,
                domain=item.domain,
                url=item.url,
                email=item.email,
                attributes={},
                provenance="profile_context" if item.source == "profile_context" else "explicit",
                confidence=item.confidence,
            )
            for item in candidate.target_entities
        ],
        timing_constraints=[
            TimingConstraint(
                kind=item.kind,
                start=item.start,
                end=item.end,
                label=item.label,
                provenance="explicit",
                confidence=item.confidence,
            )
            for item in candidate.timing_constraints
        ],
        constraints=[item.text for item in candidate.constraints],
        forbidden_canonical_outcomes=[item.outcome for item in candidate.forbidden_outcomes],
        forbidden_outcomes=[item.outcome for item in candidate.forbidden_outcomes],
        success_criteria=[
            SuccessCriterion(description=item.description, measurable=item.measurable)
            for item in candidate.success_criteria
        ],
        urgency=candidate.urgency,
        approval_preference=candidate.approval_preference,
        context_requirements=[item.requirement for item in candidate.context_requirements],
        ambiguity=clarifications,
        interpreted_clauses=interpreted_clauses,
        unmatched_material_clauses=unmatched_clauses,
        semantic_units=semantic_units,
        unmatched_material_units=unmatched_units,
        contradictions=[
            Contradiction(
                field_path=item.field_path,
                first_span=item.first_span,
                second_span=item.second_span,
                first_value=item.first_value,
                second_value=item.second_value,
                risk=item.risk,
                resolution_status="unresolved",
                rule_id="local_llm.contradiction",
            )
            for item in candidate.contradictions
        ],
        interpretation_evidence=evidence,
        coverage_score=coverage,
        minimum_field_confidence=min((item.confidence for item in evidence), default=None),
        interpretation_ready=False,
        components_available=["local_llm", "json_schema", "meaning_guard"],
        components_executed=["local_llm", "json_schema", "meaning_guard"],
        components_contributing=["local_llm", "json_schema", "meaning_guard"],
        components_active=["local_llm", "json_schema", "meaning_guard"],
    )
    readiness = evaluate_interpretation_readiness(intent)
    return intent.model_copy(
        update={
            "interpretation_ready": readiness.ready,
            "interpretation_readiness_reasons": list(readiness.reasons),
        }
    )


def _segment_coverage(*, instruction: str, candidate: LlmMissionInterpretation) -> float:
    source = _normalize_source(instruction)
    if not source:
        return 0.0
    covered = [False] * len(source)
    for segment in candidate.segments:
        needle = _normalize_source(segment.source_text)
        if not needle:
            continue
        starts: list[int] = []
        offset = 0
        while True:
            found = source.find(needle, offset)
            if found < 0:
                break
            starts.append(found)
            offset = found + 1
        if not starts:
            continue
        start = max(starts, key=lambda value: sum(not covered[index] for index in range(value, value + len(needle))))
        for index in range(start, start + len(needle)):
            covered[index] = True
    material_indexes = [index for index, char in enumerate(source) if char.isalnum()]
    if not material_indexes:
        return 1.0
    covered_material = sum(covered[index] for index in material_indexes)
    return round(covered_material / len(material_indexes), 4)


__all__ = [
    "LlmMissionInterpreter",
    "MissionInterpreter",
    "MissionInterpreterOutputError",
    "MissionInterpreterTransportError",
    "build_mission_interpreter",
]
