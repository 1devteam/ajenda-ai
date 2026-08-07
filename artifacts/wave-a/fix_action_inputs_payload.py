#!/usr/bin/env python3
"""Fix mypy no-redef on payload in action_inputs.py.

Keeps first annotated assignment; strips type annotation from later ones
in the same function scope (mypy treats annotated assignment as definition).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TARGET = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/services/mission_composition/action_inputs.py")

def main() -> None:
    text = TARGET.read_text()
    pattern = re.compile(r"payload:\s*dict\[str,\s*Any\]\s*=")
    matches = list(pattern.finditer(text))
    if len(matches) <= 1:
        print(f"= {len(matches)} annotated payload(s) — no redef to fix")
        return
    new_text = text
    for m in reversed(matches[1:]):
        new_text = new_text[: m.start()] + "payload =" + new_text[m.end() :]
    TARGET.write_text(new_text)
    print(f"OK stripped {len(matches) - 1} payload type annotation(s) in {TARGET}")


if __name__ == "__main__":
    main()
