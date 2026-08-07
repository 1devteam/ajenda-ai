"""Local-LLM mission interpreter and deterministic meaning guard."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Protocol
from urllib.parse import urlparse

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
    GroundedPolicy,
    LlmMissionInterpretation,
)
from backend.services.mission_composition.readiness import evaluate_interpretation_readiness

_WS_RE = re.compile(r"\s+")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
_INTEGER_RE = re.compile(r"\b\d+\b")
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
            if value and not _target_field_is_grounded(value=value, source_text=target.source_text, source=source):
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
    structured_emails = {target.email.casefold() for target in candidate.target_entities if target.email}

    raw_urls = {item.casefold().rstrip(".,") for item in _URL_RE.findall(instruction)}
    interpreted_urls = {item.casefold().rstrip(".,") for item in _URL_RE.findall(interpreted)}
    structured_urls = {target.url.casefold().rstrip(".,") for target in candidate.target_entities if target.url}
    structured_domains = {target.domain.casefold().strip() for target in candidate.target_entities if target.domain}

    raw_numbers = _number_facts(instruction)
    interpreted_numbers = _number_facts(interpreted)
    structured_numbers: Counter[int] = Counter()
    if candidate.requested_quantity is not None:
        structured_numbers[candidate.requested_quantity] += 1
    for target in candidate.target_entities:
        if target.radius_km is not None and float(target.radius_km).is_integer():
            structured_numbers[int(target.radius_km)] += 1

    if not raw_emails.issubset(interpreted_emails | structured_emails):
        raise MissionInterpreterOutputError(
            code="INTERPRETER_DROPPED_RECIPIENT",
            message="interpretation omitted an email address supplied by the user",
        )
    if not interpreted_emails.issubset(raw_emails):
        raise MissionInterpreterOutputError(
            code="INTERPRETER_INVENTED_RECIPIENT",
            message="interpretation introduced an email address that was not provided",
        )

    represented_urls = set(interpreted_urls) | structured_urls
    represented_url_hosts = {_url_hostname(item) for item in represented_urls}
    represented_url_hosts |= structured_domains
    represented_url_hosts.discard(None)

    dropped_urls = [
        raw_url
        for raw_url in raw_urls
        if raw_url not in represented_urls and _url_hostname(raw_url) not in represented_url_hosts
    ]
    if dropped_urls:
        raise MissionInterpreterOutputError(
            code="INTERPRETER_DROPPED_URL",
            message="interpretation omitted a URL supplied by the user",
        )
    if not interpreted_urls.issubset(raw_urls):
        raise MissionInterpreterOutputError(
            code="INTERPRETER_INVENTED_URL",
            message="interpretation introduced a URL that was not provided",
        )

    if not _counter_is_subset(raw_numbers, interpreted_numbers + structured_numbers):
        raise MissionInterpreterOutputError(
            code="INTERPRETER_DROPPED_QUANTITY",
            message="interpretation omitted a quantity supplied by the user",
        )
    if not _counter_is_subset(interpreted_numbers, raw_numbers):
        raise MissionInterpreterOutputError(
            code="INTERPRETER_INVENTED_QUANTITY",
            message="interpretation introduced a quantity that was not provided",
        )


def _url_hostname(value: str) -> str | None:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if not parsed.hostname:
        return None
    return parsed.hostname.casefold().rstrip(".")


def _target_field_is_grounded(*, value: str, source_text: str, source: str) -> bool:
    normalized_value = _normalize_source(value)
    normalized_source_text = _normalize_source(source_text)
    normalized_source = _normalize_source(source)

    if normalized_value in normalized_source_text or normalized_value in normalized_source:
        return True

    value_tokens = _meaning_tokens(value)
    if not value_tokens:
        return False

    source_tokens = _meaning_tokens(f"{source_text}\n{source}")
    return value_tokens.issubset(source_tokens)


def _meaning_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", value.casefold()):
        if token in {"a", "an", "and", "or", "the", "to", "for", "in", "near", "around", "area", "my", "our"}:
            continue
        tokens.update(_token_variants(token))
    return tokens


def _token_variants(token: str) -> set[str]:
    variants = {token}
    for suffix in ("ies", "ers", "ing", "er", "es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            stem = token[: -len(suffix)]
            variants.add(stem)
            if suffix == "ies":
                variants.add(f"{stem}y")
    return variants


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
