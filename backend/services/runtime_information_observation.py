"""Bounded, non-authoritative descriptions of mission information transitions.

Only structural metadata and content digests enter audit events. Raw prompts,
provider payloads, credentials and record values remain in their governed stores.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_SENSITIVE_KEY_FRAGMENTS = ("secret", "token", "password", "credential", "authorization", "api_key", "cookie")



def _structural_paths(value: Any, *, max_depth: int = 4, max_paths: int = 80) -> tuple[list[dict[str, Any]], bool]:
    """Explore bounded nested structure, never persisting leaf contents."""
    paths: list[dict[str, Any]] = []
    truncated = False

    def walk(item: Any, path: str, depth: int) -> None:
        nonlocal truncated
        if len(paths) >= max_paths:
            truncated = True
            return
        if isinstance(item, dict):
            kind = "object"
        elif isinstance(item, list):
            kind = "array"
        elif item is None:
            kind = "null"
        else:
            kind = type(item).__name__
        paths.append({"path": path or "$", "type": kind})
        if depth >= max_depth:
            if isinstance(item, (list, dict)) and item:
                truncated = True
            return
        if isinstance(item, dict):
            for key in sorted(item, key=str):
                name = str(key)
                if (
                    len(name) > 80
                    or not _TECHNICAL_KEY.fullmatch(name)
                    or any(fragment in name.lower() for fragment in _SENSITIVE_KEY_FRAGMENTS)
                ):
                    truncated = True
                    continue
                walk(item[key], f"{path}.{name}" if path else name, depth + 1)
        elif isinstance(item, list) and item:
            # Record array structure without duplicating potentially large record sets.
            walk(item[0], f"{path}[]" if path else "[]", depth + 1)
            if len(item) > 1:
                truncated = True

    walk(value, "", 0)
    return paths, truncated


def describe_information(value: Any) -> dict[str, Any]:
    """Describe a payload without copying its values into the observation ledger."""
    if isinstance(value, dict):
        keys = sorted(str(key) for key in value)
        public_keys = [
            key for key in keys
            if len(key) <= 80
            and _TECHNICAL_KEY.fullmatch(key)
            and not any(part in key.lower() for part in _SENSITIVE_KEY_FRAGMENTS)
        ]
        shape = "object"
        count = len(value)
    elif isinstance(value, list):
        public_keys = []
        shape = "array"
        count = len(value)
    elif value is None:
        public_keys = []
        shape = "null"
        count = 0
    else:
        public_keys = []
        shape = type(value).__name__
        count = 1
    structural_paths, nested_truncated = _structural_paths(value)
    # Fingerprint the *structure*, never raw values or secret material.
    # Canonical record references, not this digest, identify full contents.
    canonical = json.dumps(
        {"shape": shape, "count": count, "field_names": public_keys[:64], "paths": structural_paths},
        sort_keys=True, separators=(",", ":"),
    )
    return {
        "shape": shape,
        "item_count": count,
        "field_names": public_keys[:64],
        "field_name_count": len(public_keys),
        "truncated": len(public_keys) > 64 or nested_truncated,
        "structural_paths": structural_paths,
        "sha256": "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


_TECHNICAL_KEY = re.compile(r"^[a-z][a-z0-9_.-]*(?:\[\d{1,2}\][a-z0-9_.-]*)*$")


def safe_decision_keys(values: list[str], *, limit: int) -> list[str]:
    """Expose only bounded technical identifiers, never arbitrary prompt text."""
    return [
        value if len(value) <= 80 and _TECHNICAL_KEY.fullmatch(value) else "[redacted]"
        for value in values[:limit]
    ]
