"""Integrity helpers for public-API mission proof artifacts.

The digest deliberately covers the manifest payload *before* the integrity
block is added. This avoids self-referential hashes and lets an independent
reader verify one run without trusting a mutable aggregate summary.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_payload_digest(payload: dict[str, Any]) -> str:
    """Return a SHA-256 digest over the artifact payload, excluding integrity."""

    unsigned = {key: value for key, value in payload.items() if key != "integrity"}
    encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def with_integrity(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with a non-self-referential integrity declaration."""

    unsigned = {key: value for key, value in payload.items() if key != "integrity"}
    return {
        **unsigned,
        "integrity": {
            "algorithm": "sha256",
            "payload_sha256": canonical_payload_digest(unsigned),
        },
    }


def verify_integrity(payload: dict[str, Any]) -> bool:
    """Verify a proof artifact without interpreting its runtime conclusions."""

    integrity = payload.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
        return False
    claimed = integrity.get("payload_sha256")
    return isinstance(claimed, str) and claimed == canonical_payload_digest(payload)


def write_manifest(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Write an integrity-verifiable JSON proof artifact and return it."""

    artifact = with_integrity(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact
