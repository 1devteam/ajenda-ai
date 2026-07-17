#!/usr/bin/env python3
"""Smoke-test dashboard API endpoints through the Vite proxy."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

BASE = "http://localhost:5173"


def request(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict | str]:
    data = None
    req_headers = {"Content-Type": "application/json", **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def main() -> int:
    email = f"dash-api-{int(time.time())}@example.com"
    _, signup = request("POST", "/v1/onboarding/signup", {"org_name": "Dashboard Test", "email": email})
    token = signup["verification_token"]
    _, verify = request("POST", "/v1/onboarding/verify-email", {"token": token})
    tenant_id = verify["tenant_id"]
    api_key = verify["api_key"]
    headers = {"X-Tenant-Id": tenant_id, "X-Api-Key": api_key}

    checks = [
        ("account/me", "/v1/account/me"),
        ("account/plan", "/v1/account/plan"),
        ("account/usage", "/v1/account/usage"),
        ("missions", "/v1/missions?limit=50"),
        ("review-queue", "/v1/review-queue?status=pending&limit=50"),
    ]

    passed = 0
    failed = 0
    for name, path in checks:
        status, payload = request("GET", path, headers=headers)
        ok = status == 200
        print(f"{'PASS' if ok else 'FAIL'}: {name} ({status})")
        if not ok:
            print(f"  {str(payload)[:200]}")
            failed += 1
        else:
            passed += 1

    print(f"---\nDashboard API: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())