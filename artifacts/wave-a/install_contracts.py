#!/usr/bin/env python3
"""Install Wave A contracts.py from base64 parts under artifacts/wave-a/."""
from pathlib import Path
import base64
root = Path(__file__).resolve().parents[2]
parts_dir = root / "artifacts" / "wave-a"
parts = sorted(parts_dir.glob("contracts_part_*.b64"))
if not parts:
    raise SystemExit("no contracts_part_*.b64 found")
data = base64.b64decode("".join(p.read_text().strip() for p in parts))
dst = root / "backend" / "services" / "mission_composition" / "contracts.py"
dst.write_bytes(data)
text = dst.read_text()
assert 'JOB_CATALOG_VERSION = "5"' in text
assert "read_linkedin" in text
print(f"OK wrote {dst} ({len(data)} bytes)")
