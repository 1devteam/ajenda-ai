#!/usr/bin/env python3
"""Live outbound internet proof for Ajenda public-web lane.

Exercises search + page_read against the public internet when network is available.
Optional --browser / --open-write require env flags.

Exit codes:
  0 — at least one core path returned real=true
  1 — all core paths failed or returned real=false
  2 — usage / import error
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

# Repo root on sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _context():
    from backend.services.tools.schemas import ActionRuntimeContext

    return ActionRuntimeContext(
        tenant_id="internet-live-proof",
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="internet-proof-worker",
        lease_id=f"lease-{uuid.uuid4()}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Ajenda internet live proof")
    parser.add_argument("--browser", action="store_true", help="Also run web.browser_session")
    parser.add_argument("--open-write", action="store_true", help="Also run web.open_write")
    parser.add_argument("--query", default="roofing companies Fayetteville AR", help="Search query")
    parser.add_argument("--url", default="https://example.com", help="Page/browser URL")
    args = parser.parse_args()

    from backend.services.tools.action_registry import get_default_action_registry
    from backend.services.tools.schemas import ToolInvocation

    registry = get_default_action_registry(rebuild=True)
    ctx = _context()
    report: dict[str, object] = {"query": args.query, "url": args.url, "results": {}}

    # 1) Public search
    search = registry.invoke(
        ToolInvocation(action="web.search", input={"query": args.query, "limit": 5}),
        ctx,
    )
    report["results"]["web.search"] = {
        "real": search.output.get("real") or search.output.get("search_real"),
        "provider": search.output.get("search_provider") or search.output.get("provider"),
        "count": search.output.get("web_result_count"),
        "access_mode": search.output.get("access_mode"),
        "error": search.output.get("search_error"),
        "summary": search.summary,
    }

    # 2) Page read
    page = registry.invoke(
        ToolInvocation(action="web.page_read", input={"url": args.url, "timeout_seconds": 10}),
        ctx,
    )
    report["results"]["web.page_read"] = {
        "real": page.output.get("real"),
        "status_code": page.output.get("status_code"),
        "title": page.output.get("title"),
        "access_mode": page.output.get("access_mode"),
        "error": page.output.get("error"),
        "summary": page.summary,
    }

    if args.browser:
        browser = registry.invoke(
            ToolInvocation(
                action="web.browser_session",
                input={"url": args.url, "timeout_seconds": 20, "wait_until": "domcontentloaded"},
            ),
            ctx,
        )
        report["results"]["web.browser_session"] = {
            "real": browser.output.get("real"),
            "status_code": browser.output.get("status_code"),
            "title": browser.output.get("title"),
            "error": browser.output.get("error"),
            "summary": browser.summary,
        }

    if args.open_write:
        write = registry.invoke(
            ToolInvocation(
                action="web.open_write",
                input={
                    "url": "https://httpbin.org/post",
                    "method": "POST",
                    "json_body": {"proof": "ajenda-internet-live", "query": args.query},
                    "idempotency_key": f"internet-live-proof-{uuid.uuid4()}",
                    "timeout_seconds": 15,
                },
            ),
            ctx,
        )
        report["results"]["web.open_write"] = {
            "real": write.output.get("real"),
            "status_code": write.output.get("status_code"),
            "error": write.output.get("error"),
            "rate_limit_remaining": write.output.get("rate_limit_remaining"),
            "summary": write.summary,
        }

    print(json.dumps(report, indent=2, default=str))

    core_real = bool(report["results"]["web.search"].get("real")) or bool(  # type: ignore[union-attr]
        report["results"]["web.page_read"].get("real")  # type: ignore[union-attr]
    )
    if not core_real:
        print("FAIL: neither web.search nor web.page_read returned real=true", file=sys.stderr)
        return 1
    print("PASS: live internet core path returned real=true", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
