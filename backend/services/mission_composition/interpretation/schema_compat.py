"""Convert Pydantic JSON Schema into a constrained-decoding shape Ollama accepts.

Ollama/llama.cpp build a GBNF grammar from the schema. Raw Pydantic output often
includes constructs that fail grammar init (``$ref``/``$defs``, ``const``,
``anyOf`` nullables, ``minLength``/``maxLength``, ``additionalProperties``).

Ajenda still validates the model output with the full Pydantic model; this
transform only exists so the local interpreter can load the grammar.
"""

from __future__ import annotations

import copy
from typing import Any


_DROP_KEYS = frozenset(
    {
        "title",
        "description",
        "default",
        "examples",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
        "exclusiveMinimum",
        "exclusiveMaximum",
    }
)


def constrained_decoding_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return an Ollama-compatible copy of a JSON Schema document."""

    defs = schema.get("$defs") or schema.get("definitions") or {}
    cleaned = _sanitize(copy.deepcopy(schema), defs=defs, visiting=set())
    if isinstance(cleaned, dict):
        cleaned.pop("$defs", None)
        cleaned.pop("definitions", None)
        cleaned.pop("$schema", None)
        cleaned.pop("$id", None)
        # Force material top-level keys into required so constrained decoding
        # cannot omit them when Pydantic treats them as defaulted.
        properties = cleaned.get("properties")
        if isinstance(properties, dict):
            required = list(cleaned.get("required") or [])
            for key in (
                "schema_version",
                "interpreted_instruction",
                "requested_outcomes",
                "send_policy",
                "contact_policy",
                "publish_policy",
                "write_policy",
                "target_entities",
                "success_criteria",
                "segments",
            ):
                if key in properties and key not in required:
                    required.append(key)
            cleaned["required"] = required
    return cleaned  # type: ignore[return-value]


def _sanitize(node: Any, *, defs: dict[str, Any], visiting: set[str]) -> Any:
    if isinstance(node, list):
        return [_sanitize(item, defs=defs, visiting=visiting) for item in node]
    if not isinstance(node, dict):
        return node

    ref = node.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        if name in visiting:
            # Break cycles; object is the safest constrained fallback.
            return {"type": "object"}
        target = defs.get(name)
        if not isinstance(target, dict):
            return {"type": "object"}
        nested = visiting | {name}
        return _sanitize(copy.deepcopy(target), defs=defs, visiting=nested)

    if "const" in node and "enum" not in node:
        node = {**node, "enum": [node["const"]]}
        node.pop("const", None)

    if "anyOf" in node and isinstance(node["anyOf"], list):
        options = [_sanitize(item, defs=defs, visiting=visiting) for item in node["anyOf"]]
        non_null = [item for item in options if not (isinstance(item, dict) and item.get("type") == "null")]
        has_null = any(isinstance(item, dict) and item.get("type") == "null" for item in options)
        if has_null and len(non_null) == 1 and isinstance(non_null[0], dict):
            base = dict(non_null[0])
            base_type = base.get("type")
            if isinstance(base_type, str):
                base["type"] = [base_type, "null"]
            elif isinstance(base_type, list) and "null" not in base_type:
                base["type"] = [*base_type, "null"]
            # Preserve sibling keys other than anyOf from the original node.
            for key, value in node.items():
                if key in {"anyOf", "const"} or key in _DROP_KEYS:
                    continue
                if key not in base:
                    base[key] = _sanitize(value, defs=defs, visiting=visiting)
            return base
        return {
            key: (_sanitize(value, defs=defs, visiting=visiting) if key != "anyOf" else options)
            for key, value in node.items()
            if key not in _DROP_KEYS and key != "const"
        }

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DROP_KEYS or key in {"$defs", "definitions", "$schema", "$id"}:
            continue
        if key == "additionalProperties" and value is False:
            # GBNF backends often fail or explode on additionalProperties=false
            # for large nested objects; validation still forbids extras later.
            continue
        if key == "const":
            out["enum"] = [value]
            continue
        out[key] = _sanitize(value, defs=defs, visiting=visiting)
    return out
