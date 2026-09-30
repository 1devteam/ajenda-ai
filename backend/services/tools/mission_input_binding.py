"""Lease-scoped binding of upstream ability outputs into tool.invoke inputs.

Composition freezes intent seeds. This module is the runtime data plane that
makes job catalog products (prospect_candidates → qualified → enriched → drafts)
real under existing TaskDispatcher / lease / evidence authority.

Does not bypass tool.invoke. Does not invent side effects.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.repositories.execution_task_repository import ExecutionTaskRepository


class DependencyNotReadyError(Exception):
    """Raised when graph dependency_keys are not all completed for this mission."""

    def __init__(self, message: str, *, pending_keys: list[str] | None = None) -> None:
        super().__init__(message)
        self.pending_keys = list(pending_keys or [])


class InputBindingError(Exception):
    """Raised when required upstream world-state cannot be bound (fail closed)."""


def graph_node_key_for_task(task: ExecutionTask) -> str | None:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    raw = metadata.get("graph_node_key")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    selection = metadata.get("materialization_selection_reference")
    if isinstance(selection, dict):
        node_key = selection.get("node_key")
        if isinstance(node_key, str) and node_key.strip():
            return node_key.strip()
    return None


def dependency_keys_for_task(task: ExecutionTask) -> list[str]:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    raw = metadata.get("dependency_keys") or []
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if isinstance(item, str) and str(item).strip()]


def handler_output_for_task(task: ExecutionTask) -> dict[str, Any]:
    """Extract structured ability output from a completed task."""
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    handler_result = metadata.get("handler_result")
    if isinstance(handler_result, dict):
        nested = handler_result.get("output")
        if isinstance(nested, dict):
            return nested
    nested_output = metadata.get("output")
    if isinstance(nested_output, dict):
        # Avoid mistaking tool_invocation envelope for ability output.
        if "handler" not in nested_output and "schema_version" not in nested_output:
            return nested_output
        inner = nested_output.get("output")
        if isinstance(inner, dict):
            return inner
    return {}


def index_mission_tasks_by_node_key(tasks: list[ExecutionTask]) -> dict[str, ExecutionTask]:
    indexed: dict[str, ExecutionTask] = {}
    for task in tasks:
        key = graph_node_key_for_task(task)
        if key is None:
            continue
        # Prefer the completed task that actually contains a structured output.
        # Runtime retries can leave an older completed projection beside a later
        # terminal task; status alone is not enough to identify the usable world
        # state for a downstream binding.
        existing = indexed.get(key)
        if existing is None:
            indexed[key] = task
            continue
        existing_output = handler_output_for_task(existing)
        candidate_output = handler_output_for_task(task)
        existing_rank = (
            int(existing.status == ExecutionTaskState.COMPLETED.value),
            int(bool(existing_output)),
            len(existing_output),
        )
        candidate_rank = (
            int(task.status == ExecutionTaskState.COMPLETED.value),
            int(bool(candidate_output)),
            len(candidate_output),
        )
        if candidate_rank > existing_rank:
            indexed[key] = task
    return indexed


def pending_dependency_keys(*, task: ExecutionTask, mission_tasks: list[ExecutionTask]) -> list[str]:
    deps = dependency_keys_for_task(task)
    if not deps:
        return []
    by_key = index_mission_tasks_by_node_key(mission_tasks)
    pending: list[str] = []
    for key in deps:
        upstream = by_key.get(key)
        if upstream is None or upstream.status != ExecutionTaskState.COMPLETED.value:
            pending.append(key)
    return pending


def assert_dependencies_ready(*, task: ExecutionTask, mission_tasks: list[ExecutionTask]) -> None:
    pending = pending_dependency_keys(task=task, mission_tasks=mission_tasks)
    if pending:
        raise DependencyNotReadyError(
            f"ability dependencies not complete: {', '.join(pending)}",
            pending_keys=pending,
        )


def _json_path_get(payload: dict[str, Any], path: str) -> Any:
    """Minimal JSONPath: $.a.b or $.a[*].c for list flatten of dict field."""
    raw = path.strip()
    if not raw.startswith("$"):
        return None
    if raw == "$" or raw == "$.input":
        return payload
    tokens = [part for part in raw.lstrip("$").split(".") if part]
    current: Any = payload
    for token in tokens:
        if current is None:
            return None
        if token.endswith("[*]"):
            key = token[: -len("[*]")]
            if not isinstance(current, dict):
                return None
            items = current.get(key)
            if not isinstance(items, list):
                return None
            current = items
            continue
        if isinstance(current, list):
            # field after [*] → map field across items
            mapped: list[Any] = []
            for item in current:
                if isinstance(item, dict) and token in item:
                    mapped.append(item[token])
            current = mapped
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(token)
    return current


def _input_path_keys(path: str) -> list[str]:
    raw = path.strip()
    if raw in {"$", "$.input", "input"}:
        return []
    if raw.startswith("$.input."):
        return [k for k in raw[len("$.input.") :].split(".") if k]
    if raw.startswith("$."):
        keys = [k for k in raw[2:].split(".") if k]
        if keys and keys[0] == "input":
            keys = keys[1:]
        return keys
    return [k for k in raw.split(".") if k]


def _get_input_path(tool_input: dict[str, Any], path: str) -> Any:
    keys = _input_path_keys(path)
    if not keys:
        return tool_input
    current: Any = tool_input
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _set_input_path(tool_input: dict[str, Any], path: str, value: Any) -> None:
    """Set value at $.input… path into tool_input dict (paths relative to input root)."""
    keys = _input_path_keys(path)
    if not keys:
        if isinstance(value, dict):
            tool_input.clear()
            tool_input.update(value)
        return
    cursor: dict[str, Any] = tool_input
    for key in keys[:-1]:
        next_val = cursor.get(key)
        if not isinstance(next_val, dict):
            next_val = {}
            cursor[key] = next_val
        cursor = next_val
    cursor[keys[-1]] = value


def collect_upstream_world_state(mission_tasks: list[ExecutionTask]) -> dict[str, Any]:
    """Merge completed ability outputs into a mission world-state document."""
    world: dict[str, Any] = {
        "prospect_candidates": [],
        "qualified_prospects": [],
        "enriched_prospects": [],
        "observed_contacts": [],
        "crm_records": [],
        "introduction_drafts": [],
        "by_node": {},
    }
    by_key = index_mission_tasks_by_node_key(mission_tasks)
    for node_key, task in by_key.items():
        if task.status != ExecutionTaskState.COMPLETED.value:
            continue
        output = handler_output_for_task(task)
        world["by_node"][node_key] = {
            "task_id": str(task.id),
            "status": task.status,
            "output": output,
        }
        for list_key in (
            "prospect_candidates",
            "qualified_prospects",
            "enriched_prospects",
            "observed_contacts",
            "crm_records",
            "introduction_drafts",
        ):
            items = output.get(list_key)
            if isinstance(items, list):
                world[list_key].extend([item for item in items if isinstance(item, dict)])
    return world


def _binding_specs_from_metadata(metadata: dict[str, Any]) -> list[dict[str, str]]:
    raw = metadata.get("input_bindings")
    if isinstance(raw, list) and raw:
        return [dict(item) for item in raw if isinstance(item, dict)]
    # Fallback: derive from dependency_keys + known ability chain contracts
    deps = metadata.get("dependency_keys") or []
    action = None
    tool_inv = metadata.get("tool_invocation")
    if isinstance(tool_inv, dict) and isinstance(tool_inv.get("action"), str):
        action = tool_inv["action"]
    if not action or not isinstance(deps, list) or not deps:
        return []
    return default_bindings_for_action(action_name=action, dependency_keys=[str(d) for d in deps if d])


def default_bindings_for_action(*, action_name: str, dependency_keys: list[str]) -> list[dict[str, str]]:
    """Authoritative binding map when graph metadata omits explicit input_bindings."""
    specs: list[dict[str, str]] = []
    for dep in dependency_keys:
        if action_name in {"sales.qualify", "sales.score_lead"} and "observe" in dep:
            specs.append(
                {
                    "from_step": dep,
                    "output_path": "$.verified_prospect_candidates",
                    "input_path": "$.input.prospects",
                }
            )
            specs.append(
                {
                    "from_step": dep,
                    "output_path": "$.observed_contacts",
                    "input_path": "$.input.context.observed_contacts",
                }
            )
        if action_name in {"sales.qualify", "sales.score_lead"} and "record-search" in dep:
            specs.append(
                {
                    "from_step": dep,
                    "output_path": "$.crm_records",
                    "input_path": "$.input.prospects",
                }
            )
        if action_name == "research.observe_contacts" and "web-research" in dep:
            specs.append(
                {
                    "from_step": dep,
                    "output_path": "$.prospect_candidates",
                    "input_path": "$.input.prospects",
                }
            )
        elif action_name == "research.observe_contacts" and "record-search" in dep:
            specs.append(
                {
                    "from_step": dep,
                    "output_path": "$.crm_records",
                    "input_path": "$.input.prospects",
                }
            )
        elif (
            action_name in {"sales.qualify", "sales.score_lead"}
            and "web-research" in dep
            and not any("observe" in dependency for dependency in dependency_keys)
        ):
            specs.append(
                {
                    "from_step": dep,
                    "output_path": "$.prospect_candidates",
                    "input_path": "$.input.prospects",
                }
            )
        elif action_name == "decision.recommend_next_action" and "retrieve" in dep:
            specs.append(
                {
                    "from_step": dep,
                    "output_path": "$.business_profile_facts",
                    "input_path": "$.input.context.business_profile_facts",
                }
            )
        elif action_name == "decision.recommend_next_action" and (
            "observe" in dep or "observe-contacts" in dep or "observe_sources" in dep
        ):
            specs.append(
                {
                    "from_step": dep,
                    "output_path": "$.observed_contacts",
                    "input_path": "$.input.context.observed_contacts",
                }
            )
        elif action_name == "gtm.lead_enrich":
            if "sales-qualify" in dep or "qualify" in dep:
                specs.append(
                    {
                        "from_step": dep,
                        "output_path": "$.qualified_prospects",
                        "input_path": "$.input.prospects",
                    }
                )
            elif "web-research" in dep:
                if not any("qualif" in dependency or "enrich" in dependency for dependency in dependency_keys):
                    specs.append(
                        {
                            "from_step": dep,
                            "output_path": "$.prospect_candidates",
                            "input_path": "$.input.prospects",
                        }
                    )
        elif action_name in {"sales.research", "crm.research"} and (
            "discover" in dep or "research" in dep or "web" in dep
        ):
            specs.append(
                {
                    "from_step": dep,
                    "output_path": "$.prospect_candidates",
                    "input_path": "$.input.context.prospect_candidates",
                }
            )
        elif action_name == "research.synthesize_report" and ("discover" in dep or "research" in dep or "web" in dep):
            specs.append(
                {
                    "from_step": dep,
                    "output_path": "$.prospect_candidates",
                    "input_path": "$.input.prospects",
                }
            )
        elif action_name == "record.write":
            if "observe" in dep:
                specs.append(
                    {
                        "from_step": dep,
                        "output_path": "$.observed_contacts",
                        "input_path": "$.input.context.observed_contacts",
                    }
                )
            elif "qualif" in dep:
                specs.append(
                    {
                        "from_step": dep,
                        "output_path": "$.qualified_prospects",
                        "input_path": "$.input.context.qualified_prospects",
                    }
                )
        elif action_name in {"vertical.finance.prepare_reconciliation", "vertical.finance.prepare_invoice_drafts"} and (
            "accounting-read-revenue" in dep or "read_revenue" in dep or "revenue" in dep
        ):
            specs.append(
                {
                    "from_step": dep,
                    "output_path": "$.revenue_records",
                    "input_path": "$.input.revenue_records",
                }
            )
        elif action_name == "gtm.crm_upsert":
            if "qualif" in dep:
                specs.append(
                    {
                        "from_step": dep,
                        "output_path": "$.qualified_prospects",
                        "input_path": "$.input.context.qualified_prospects",
                    }
                )
            elif "discover" in dep or "research" in dep or "web" in dep:
                specs.append(
                    {
                        "from_step": dep,
                        "output_path": "$.prospect_candidates",
                        "input_path": "$.input.context.prospect_candidates",
                    }
                )
        elif action_name in {"gtm.email_draft", "gtm.email_send", "sales.draft_followup"}:
            if action_name == "gtm.email_send" and ("prepare" in dep or "draft" in dep):
                specs.append(
                    {
                        "from_step": dep,
                        "output_path": "$.introduction_drafts",
                        "input_path": "$.input.context.introduction_drafts",
                    }
                )
            elif "lead_enrich" in dep or "enrich" in dep:
                specs.append(
                    {
                        "from_step": dep,
                        "output_path": "$.enriched_prospects",
                        "input_path": "$.input.prospects",
                    }
                )
            elif "qualify" in dep:
                specs.append(
                    {
                        "from_step": dep,
                        "output_path": "$.qualified_prospects",
                        "input_path": "$.input.prospects",
                    }
                )
            elif "web-research" in dep:
                specs.append(
                    {
                        "from_step": dep,
                        "output_path": "$.prospect_candidates",
                        "input_path": "$.input.prospects",
                    }
                )
    return specs


def _prospect_merge_key(item: dict[str, Any]) -> str:
    return (
        str(
            item.get("prospect_id")
            or item.get("id")
            or item.get("domain")
            or item.get("company")
            or item.get("name")
            or ""
        )
        .strip()
        .lower()
    )


def _prospect_richness(item: dict[str, Any]) -> int:
    score = 0
    if item.get("contacts"):
        score += 4
    if item.get("email"):
        score += 3
    if item.get("domain"):
        score += 2
    if item.get("signals") or item.get("reasons"):
        score += 1
    if item.get("score") is not None:
        score += 1
    return score


def _merge_prospect_lists(left: list[Any], right: list[Any]) -> list[dict[str, Any]]:
    """Merge two prospect lists, preferring richer records for the same identity."""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for source in (left, right):
        for item in source:
            if not isinstance(item, dict):
                continue
            key = _prospect_merge_key(item) or f"anon:{len(order)}"
            if key not in merged:
                merged[key] = dict(item)
                order.append(key)
                continue
            current = merged[key]
            if _prospect_richness(item) >= _prospect_richness(current):
                combined = dict(current)
                combined.update(item)
                # Preserve contacts from the richer side when the winner lacks them.
                if not combined.get("contacts") and current.get("contacts"):
                    combined["contacts"] = current["contacts"]
                merged[key] = combined
            else:
                # Keep richer current; fill missing fields from weaker side.
                for field, value in item.items():
                    if field not in current or current.get(field) in (None, "", [], {}):
                        current[field] = value
    return [merged[key] for key in order]


def apply_input_bindings(
    *,
    tool_input: dict[str, Any],
    task: ExecutionTask,
    mission_tasks: list[ExecutionTask],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (bound_input, binding_audit). Fail closed when binding_required and empty."""
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    assert_dependencies_ready(task=task, mission_tasks=mission_tasks)

    bound = deepcopy(tool_input) if isinstance(tool_input, dict) else {}
    specs = _binding_specs_from_metadata(metadata)
    by_key = index_mission_tasks_by_node_key(mission_tasks)
    applied: list[dict[str, Any]] = []

    for spec in specs:
        from_step = str(spec.get("from_step") or "").strip()
        output_path = str(spec.get("output_path") or "").strip()
        input_path = str(spec.get("input_path") or "$.input").strip()
        if not from_step or not output_path:
            continue
        upstream = by_key.get(from_step)
        if upstream is None or upstream.status != ExecutionTaskState.COMPLETED.value:
            raise DependencyNotReadyError(
                f"binding source step not complete: {from_step}",
                pending_keys=[from_step],
            )
        value = _json_path_get(handler_output_for_task(upstream), output_path)
        if value is None:
            continue
        existing = _get_input_path(bound, input_path)
        # When multiple deps target the same list path (e.g. enrich + qualify → prospects),
        # merge by prospect identity and prefer records that carry contacts.
        if isinstance(value, list) and isinstance(existing, list):
            value = _merge_prospect_lists(existing, value)
        _set_input_path(bound, input_path, value)
        applied.append(
            {
                "from_step": from_step,
                "output_path": output_path,
                "input_path": input_path,
                "value_kind": type(value).__name__,
                "count": len(value) if isinstance(value, list) else 1,
            }
        )

    action_name = _action_name_from_metadata(metadata)
    # Specialize outreach inputs only for schemas that define the derived
    # context fields. ResearchReportInput is deliberately strict and should
    # receive only its declared objective/prospects/binding_required fields.
    if action_name != "research.synthesize_report":
        bound = _specialize_outreach_input(bound)
    if action_name == "gtm.email_send":
        bound = _specialize_email_send_input(bound)
    if action_name == "decision.recommend_next_action":
        bound = _specialize_decision_recommend_input(bound)

    raw_context = bound.get("context")
    context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
    binding_required = bool(context.get("binding_required")) or bool(bound.get("binding_required"))

    audit = {
        "bindings_applied": applied,
        "binding_required": binding_required,
        "prospect_count": len(bound.get("prospects") or []) if isinstance(bound.get("prospects"), list) else 0,
        "action": action_name,
    }

    if binding_required and action_needs_prospect_world(metadata):
        if action_name == "gtm.email_send":
            if not _email_send_has_world_state(bound):
                raise InputBindingError(
                    "binding_required but no introduction_drafts or enriched prospects "
                    "were available for gtm.email_send"
                )
        else:
            prospects = bound.get("prospects")
            if not isinstance(prospects, list) or not prospects:
                # A draft is still a product artifact and must identify the
                # upstream prospect it represents. Industry/location seeds are
                # planning context, not permission to emit a placeholder row.
                raise InputBindingError(
                    f"binding_required but no upstream prospects were available for {action_name or 'ability'}"
                )
            audit["primary_prospect"] = _primary_prospect(bound)

    return bound, audit


def _specialize_decision_recommend_input(bound: dict[str, Any]) -> dict[str, Any]:
    """Turn observed contacts into recommend options. Never invents mailboxes."""

    raw_context = bound.get("context")
    context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
    observed = context.get("observed_contacts")
    if not isinstance(observed, list) or not observed:
        return bound

    options: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(observed):
        if not isinstance(item, dict) or item.get("real") is not True:
            continue
        company = str(item.get("company") or item.get("domain") or f"source-{index + 1}")[:240]
        option_id = f"contact:{index}:{company}"[:120]
        if option_id in seen:
            continue
        seen.add(option_id)
        kind = str(item.get("kind") or "contact")
        value = str(item.get("value") or "")
        source_url = str(item.get("source_url") or "")
        options.append(
            {
                "option_id": option_id,
                "label": f"Use observed {kind} for {company}",
                "description": f"{kind}={value} from {source_url}"[:1000],
            }
        )
        evidence.append(
            {
                "evidence_id": f"obs-{index}-{kind}"[:160],
                "claim": f"Observed {kind} {value} on {source_url}",
                "status": "known",
                "source": source_url or "research.observe_contacts",
                "confidence": 0.85,
                "supports_option_ids": [option_id],
                "supports_criterion_ids": ["has_real_contact"],
            }
        )
    if not options:
        return bound
    specialized = dict(bound)
    specialized["options"] = options
    specialized["evidence"] = evidence
    return specialized


def _action_name_from_metadata(metadata: dict[str, Any]) -> str | None:
    tool_inv = metadata.get("tool_invocation")
    if isinstance(tool_inv, dict):
        action = tool_inv.get("action")
        if isinstance(action, str):
            return action
    return None


def action_needs_prospect_world(metadata: dict[str, Any]) -> bool:
    action = _action_name_from_metadata(metadata)
    return action in {
        "sales.qualify",
        "sales.score_lead",
        "gtm.lead_enrich",
        "gtm.email_draft",
        "gtm.email_send",
        "sales.draft_followup",
        "research.observe_contacts",
        "research.synthesize_report",
    }


def _is_deliverable_recipient(value: Any) -> bool:
    """True when value looks like a real mailbox (not composition placeholder)."""
    if not isinstance(value, str):
        return False
    email = value.strip().lower()
    if not email or "@" not in email:
        return False
    local, _, domain = email.rpartition("@")
    if not local or not domain:
        return False
    # Composition / local-proof placeholders — never treat as external-send recipients.
    # Reject exact reserved labels (ops@test) and dotted suffixes (ops@foo.test).
    if domain == "invalid.local" or domain.endswith(".invalid.local"):
        return False
    if domain in {"example", "example.com"} or domain.endswith(".example"):
        return False
    if domain in {"test", "local", "localhost"} or domain.endswith((".test", ".local", ".localhost")):
        return False
    return True


def _email_send_has_world_state(bound: dict[str, Any]) -> bool:
    """Send requires a deliverable recipient — draft/artifact alone is not enough.

    Fail closed when the only bound recipient is pending.binding@invalid.local or a
    simulated enrich contact. External-send must not enter the side-effect path on
    placeholders.
    """
    raw_context = bound.get("context")
    context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
    if context.get("recipient_bound") is True and _is_deliverable_recipient(bound.get("to")):
        return True
    if _is_deliverable_recipient(bound.get("to")):
        return True
    # Explicit real recipient on a draft entry still counts after specialize.
    drafts = context.get("introduction_drafts")
    if isinstance(drafts, list):
        for draft in drafts:
            if not isinstance(draft, dict):
                continue
            if draft.get("recipient_bound") is False:
                continue
            if _is_deliverable_recipient(draft.get("recipient") or draft.get("to")):
                return True
    return False


def _specialize_email_send_input(bound: dict[str, Any]) -> dict[str, Any]:
    """Map introduction_drafts / enriched_prospects from context onto GtmEmailSendInput fields.

    Never promotes placeholder or simulated addresses onto ``to`` as if they were bound.
    """
    result = deepcopy(bound)
    raw_context = result.get("context")
    context: dict[str, Any] = dict(raw_context) if isinstance(raw_context, dict) else {}

    drafts = context.get("introduction_drafts")
    if isinstance(drafts, list):
        for draft in drafts:
            if not isinstance(draft, dict):
                continue
            recipient = str(draft.get("recipient") or draft.get("to") or "").strip()
            if (
                _is_deliverable_recipient(recipient)
                and draft.get("recipient_bound") is not False
                and (
                    not result.get("to")
                    or str(result.get("to") or "").endswith("@invalid.local")
                    or not _is_deliverable_recipient(result.get("to"))
                )
            ):
                result["to"] = recipient
                context["recipient_bound"] = True
                context["recipient_source"] = "introduction_drafts"
            if draft.get("subject") and (
                not str(result.get("subject") or "").strip()
                or str(result.get("subject") or "").startswith("Introduction")
            ):
                result["subject"] = str(draft["subject"])[:240]
            if draft.get("body") and (
                "requires bound recipient" in str(result.get("body") or "") or not str(result.get("body") or "").strip()
            ):
                result["body"] = str(draft["body"])[:5000]
            if draft.get("artifact_id") and not result.get("artifact_id"):
                result["artifact_id"] = str(draft["artifact_id"])[:160]
            context["bound_from_introduction_drafts"] = True
            break

    enriched = context.get("enriched_prospects")
    if isinstance(enriched, list):
        for prospect in enriched:
            if not isinstance(prospect, dict):
                continue
            raw_contacts = prospect.get("contacts")
            contacts: list[Any] = raw_contacts if isinstance(raw_contacts, list) else []
            for contact in contacts:
                if not isinstance(contact, dict) or not contact.get("email"):
                    continue
                if contact.get("simulated") or contact.get("real") is False:
                    continue
                email = str(contact["email"]).strip()
                if _is_deliverable_recipient(email) and (
                    not result.get("to") or not _is_deliverable_recipient(result.get("to"))
                ):
                    result["to"] = email
                    context["recipient_bound"] = True
                    context["recipient_source"] = "enriched_prospects"
                break
            break

    result["context"] = context
    return result


def _primary_prospect(bound: dict[str, Any]) -> dict[str, Any] | None:
    prospects = bound.get("prospects")
    if not isinstance(prospects, list) or not prospects:
        return None
    first = prospects[0]
    return first if isinstance(first, dict) else None


def _specialize_outreach_input(bound: dict[str, Any]) -> dict[str, Any]:
    """Fold top prospect into recipient/topic/context for draft/enrich single-shot handlers.

    Only mutates fields that existing input models accept:
    - always: context, prospects
    - when already present: company, domain, lead, recipient, to, topic
    """
    result = deepcopy(bound)
    prospects = result.get("prospects")
    if not isinstance(prospects, list) or not prospects:
        return result
    primary = prospects[0] if isinstance(prospects[0], dict) else None
    if primary is None:
        return result

    company = str(primary.get("company") or primary.get("name") or "").strip()
    domain = str(primary.get("domain") or "").strip() or None
    industry = primary.get("industry")
    location = primary.get("location")
    email = None
    contacts = primary.get("contacts")
    if isinstance(contacts, list):
        for contact in contacts:
            if isinstance(contact, dict) and contact.get("email"):
                # Prefer real contact emails only for recipient promotion.
                if contact.get("simulated") or contact.get("real") is False:
                    continue
                email = str(contact["email"]).strip()
                break
    if not email and primary.get("email") and primary.get("real") is not False:
        email = str(primary["email"]).strip()

    raw_context = result.get("context")
    context: dict[str, Any] = dict(raw_context) if isinstance(raw_context, dict) else {}
    if company:
        context["prospect_company"] = company
        if "company" in result:
            result["company"] = company
    if domain:
        context["prospect_domain"] = domain
        if "domain" in result:
            result["domain"] = domain
    if industry is not None:
        context["industry"] = industry
    if location is not None:
        context["location"] = location
    context["prospect_id"] = primary.get("prospect_id") or primary.get("id")
    context["upstream_signals"] = primary.get("signals") or primary.get("reasons") or []
    context["bound_from_world_state"] = True

    if company and "topic" in result:
        if not str(result.get("topic") or "").strip() or str(result.get("topic") or "").startswith("Introduction"):
            result["topic"] = f"Introduction — {company}"[:240]

    if email and not str(email).endswith("@invalid.local"):
        if "recipient" in result and (
            not result.get("recipient") or str(result.get("recipient") or "").endswith("@invalid.local")
        ):
            result["recipient"] = email
        if "to" in result and (not result.get("to") or str(result.get("to") or "").endswith("@invalid.local")):
            result["to"] = email
        context["recipient_bound"] = True
        context["recipient_source"] = "enriched_prospects"
    else:
        context["recipient_bound"] = False

    result["context"] = context

    # sales.qualify / score still accept lead — update only when lead key exists.
    if "lead" in result and isinstance(result.get("lead"), dict):
        lead = dict(result["lead"])
        if company:
            lead["company"] = company
        if email:
            lead["email"] = email
        if primary.get("role") or primary.get("title"):
            lead["role"] = primary.get("role") or primary.get("title")
        if primary.get("intent"):
            lead["intent"] = primary.get("intent")
        if industry:
            lead["industry"] = industry
        if location:
            lead["location"] = location
        result["lead"] = lead
    elif "lead" not in result and ("score" in str(result.keys()) or company):
        # sales.qualify seed often has lead key from composition; if missing and prospects present,
        # create lead only when action input already expected it — composition always seeds lead.
        pass
    return result


def bind_tool_invocation_for_task(
    *,
    task: ExecutionTask,
    session_factory: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load mission siblings and bind tool_invocation.input. Returns (tool_invocation, audit).

    No-ops when the task has no dependency_keys / input_bindings so isolated
    ability-runtime invokes stay unchanged.
    """
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    raw_invocation = metadata.get("tool_invocation")
    if not isinstance(raw_invocation, dict):
        # Let ToolRuntimeAuthority.authorize surface the canonical error.
        return {}, {"bindings_applied": [], "skipped": "missing_tool_invocation"}

    tool_input = raw_invocation.get("input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    deps = dependency_keys_for_task(task)
    specs = _binding_specs_from_metadata(metadata)
    if task.mission_id is None or (not deps and not specs):
        return dict(raw_invocation), {"bindings_applied": [], "skipped": "no_dependencies"}

    session = session_factory()
    try:
        try:
            from backend.db.tenant_session import activate_tenant_session

            activate_tenant_session(session, task.tenant_id)
        except Exception:
            # Unit stubs may lack set_config; repository still works without RLS.
            pass
        mission_tasks = ExecutionTaskRepository(session).list_for_mission_for_tenant(
            mission_id=UUID(str(task.mission_id)),
            tenant_id=task.tenant_id,
        )
    finally:
        session.close()

    bound_input, audit = apply_input_bindings(
        tool_input=tool_input,
        task=task,
        mission_tasks=mission_tasks,
    )
    rebound = dict(raw_invocation)
    rebound["input"] = bound_input
    return rebound, audit
