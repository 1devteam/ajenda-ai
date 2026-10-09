"""External/internal effect receipts and limitations for RevOps deliverables."""

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from backend.domain.enums import ExecutionTaskState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.services.mission_composition.revops_deliverable_contracts import RevOpsEffectRead
from backend.services.mission_composition.revops_deliverable_prospects import (
    _handler_result,
    _nonempty_text,
    _string_tuple,
    _task_action,
)
from backend.services.tools.schemas import SideEffectClass


def _receipt_from_output(
    *,
    output: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any] | None:
    receipt: dict[str, Any] = {}
    for key in ("idempotency_key", "provider_message_id", "artifact_id", "post_id", "url", "id"):
        value = output.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            receipt[key] = value
    records_changed = result.get("records_changed")
    if isinstance(records_changed, list):
        normalized = [str(item) for item in records_changed if str(item).strip()]
        if normalized:
            receipt["records_changed"] = normalized
    real_response = output.get("real_response")
    if isinstance(real_response, dict) and isinstance(real_response.get("status_code"), int):
        receipt["provider_status_code"] = real_response["status_code"]
    return receipt or None


def _effects(
    *,
    tasks: Sequence[ExecutionTask],
    evidence_records: Sequence[EvidenceRecord],
) -> tuple[RevOpsEffectRead, ...]:
    evidence_by_task: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for evidence in evidence_records:
        if evidence.execution_task_id is not None:
            evidence_by_task[evidence.execution_task_id].append(evidence.id)

    effects: list[RevOpsEffectRead] = []
    for task in sorted(tasks, key=lambda item: str(item.id)):
        result = _handler_result(task)
        raw_class = result.get("side_effect_class")
        if not isinstance(raw_class, str):
            continue
        try:
            side_effect_class = SideEffectClass(raw_class)
        except ValueError:
            continue
        if not side_effect_class.has_side_effect:
            continue
        output = result.get("output")
        output = dict(output) if isinstance(output, dict) else {}
        real = output.get("real") is True
        receipt = _receipt_from_output(output=output, result=result) if real else None
        if not real:
            receipt_status: Literal["recorded", "missing", "simulated", "not_applicable"] = "simulated"
        elif receipt is None:
            receipt_status = "missing"
        else:
            receipt_status = "recorded"
        effects.append(
            RevOpsEffectRead(
                task_id=task.id,
                action=_task_action(task),
                side_effect_class=side_effect_class,
                task_status=task.status,
                status=_nonempty_text(output.get("status")) or task.status,
                real=real,
                provider=_nonempty_text(output.get("provider") or result.get("provider")),
                receipt_status=receipt_status,
                receipt=receipt,
                evidence_ids=tuple(sorted(evidence_by_task.get(task.id, []), key=str)),
            )
        )
    return tuple(effects)


def _limitations(
    *,
    tasks: Sequence[ExecutionTask],
    evidence_records: Sequence[EvidenceRecord],
    assembly_errors: Sequence[str],
) -> tuple[str, ...]:
    values: list[str] = list(assembly_errors)
    for task in sorted(tasks, key=lambda item: str(item.id)):
        result = _handler_result(task)
        for value in _string_tuple(result.get("limitations")):
            values.append(value)
        if task.status == ExecutionTaskState.BLOCKED.value and not result:
            values.append(
                f"task {task.id} is blocked without persisted handler output; external effect state may be ambiguous"
            )
    for evidence in evidence_records:
        provenance = evidence.provenance_metadata if isinstance(evidence.provenance_metadata, dict) else {}
        for value in _string_tuple(provenance.get("limitations")):
            values.append(value)
    return tuple(dict.fromkeys(values))
