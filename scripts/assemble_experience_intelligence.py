#!/usr/bin/env python3
"""Assemble experience_intelligence.py from base64 parts. Run from repo root."""
from __future__ import annotations
import base64
import hashlib
from pathlib import Path

EXPECTED = "dc7047e3134f4aa8498dcab5f6a4beb8199b591eb1f30040dd496a301445a259"
ROOT = Path(__file__).resolve().parents[1]
PARTS = [
    ROOT / "artifacts_transport" / "experience_intelligence.part0.b64",
    ROOT / "artifacts_transport" / "experience_intelligence.part1.b64",
    ROOT / "artifacts_transport" / "experience_intelligence.part2.b64",
]
OUT = ROOT / "backend" / "services" / "ontology" / "experience_intelligence.py"

def main() -> None:
    b64 = "".join(p.read_text().strip() for p in PARTS)
    data = base64.b64decode(b64)
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED:
        raise SystemExit(f"sha256 mismatch: {digest} != {EXPECTED}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(data)
    print(f"wrote {OUT} ({len(data)} bytes) sha256={digest}")

if __name__ == "__main__":
    main()
