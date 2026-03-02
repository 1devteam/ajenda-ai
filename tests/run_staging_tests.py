"""
Citadel Staging Test Runner
Runs all integration and performance tests against https://nested-ai.net
Built with Pride for Obex Blackvault
"""
import asyncio
import sys
import os
import json
import time
from datetime import datetime
from typing import Dict, Any, List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STAGING_URL = "https://nested-ai.net"

# ============================================================================
# Auth Integration Tests (adapted from tests/integration/test_auth.py)
# ============================================================================
import httpx


class AuthTestSuite:
    """Authentication and authorization test suite against staging"""

    def __init__(self, base_url: str = STAGING_URL):
        self.base_url = base_url
        self.test_results: List[Dict[str, Any]] = []
        self.test_user_email = f"staging_auth_{int(time.time())}@nested-ai.net"
        self.test_user_password = "StagingAuth123!"
        self.access_token = None
        self.refresh_token = None
        self.test_tenant_id = None
        self.test_user_id = None

    def log(self, name: str, passed: bool, details: str = ""):
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} - {name}")
        if details:
            print(f"    Details: {details}")
        self.test_results.append({"name": name, "passed": passed, "details": details})

    async def run(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0, verify=True) as client:
            self.client = client

            # Test 1: Register
            try:
                r = await client.post(f"{self.base_url}/api/v1/auth/register", json={
                    "email": self.test_user_email,
                    "password": self.test_user_password,
                    "name": "Staging Auth Tester",
                })
                passed = r.status_code == 201
                data = r.json()
                if passed:
                    self.test_user_id = data.get("id")
                    self.test_tenant_id = data.get("tenant_id")
                self.log("User Registration", passed, f"status={r.status_code} id={data.get('id', 'N/A')}")
            except Exception as e:
                self.log("User Registration", False, str(e))

            # Test 2: Login
            try:
                r = await client.post(f"{self.base_url}/api/v1/auth/login", json={
                    "email": self.test_user_email,
                    "password": self.test_user_password,
                })
                passed = r.status_code == 200
                data = r.json()
                if passed:
                    self.access_token = data.get("access_token")
                    self.refresh_token = data.get("refresh_token")
                self.log("User Login", passed, f"status={r.status_code} token={'present' if self.access_token else 'missing'}")
            except Exception as e:
                self.log("User Login", False, str(e))

            # Test 3: Access protected endpoint with valid token
            try:
                r = await client.get(f"{self.base_url}/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {self.access_token}"})
                passed = r.status_code == 200 and r.json().get("email") == self.test_user_email
                self.log("Access Protected Endpoint", passed, f"status={r.status_code} email={r.json().get('email', 'N/A')}")
            except Exception as e:
                self.log("Access Protected Endpoint", False, str(e))

            # Test 4: Access without token (should be 401)
            try:
                r = await client.get(f"{self.base_url}/api/v1/auth/me")
                passed = r.status_code == 401
                self.log("Reject Request Without Token", passed, f"status={r.status_code} (expected 401)")
            except Exception as e:
                self.log("Reject Request Without Token", False, str(e))

            # Test 5: Access with invalid token (should be 401)
            try:
                r = await client.get(f"{self.base_url}/api/v1/auth/me",
                    headers={"Authorization": "Bearer invalid.token.here"})
                passed = r.status_code == 401
                self.log("Reject Invalid Token", passed, f"status={r.status_code} (expected 401)")
            except Exception as e:
                self.log("Reject Invalid Token", False, str(e))

            # Test 6: Refresh token
            try:
                r = await client.post(f"{self.base_url}/api/v1/auth/refresh", json={
                    "refresh_token": self.refresh_token
                })
                passed = r.status_code == 200 and bool(r.json().get("access_token"))
                new_token = r.json().get("access_token", "")
                self.log("Token Refresh", passed, f"status={r.status_code} new_token={'present' if new_token else 'missing'}")
                if passed:
                    self.access_token = new_token  # Use new token for remaining tests
            except Exception as e:
                self.log("Token Refresh", False, str(e))

            # Test 7: Wrong password rejected
            try:
                r = await client.post(f"{self.base_url}/api/v1/auth/login", json={
                    "email": self.test_user_email,
                    "password": "WrongPassword999!",
                })
                passed = r.status_code in [401, 400]
                self.log("Reject Wrong Password", passed, f"status={r.status_code} (expected 401/400)")
            except Exception as e:
                self.log("Reject Wrong Password", False, str(e))

            # Test 8: Duplicate registration rejected
            try:
                r = await client.post(f"{self.base_url}/api/v1/auth/register", json={
                    "email": self.test_user_email,
                    "password": self.test_user_password,
                    "name": "Duplicate User",
                })
                passed = r.status_code in [409, 400, 422]
                self.log("Reject Duplicate Registration", passed, f"status={r.status_code} (expected 409/400/422)")
            except Exception as e:
                self.log("Reject Duplicate Registration", False, str(e))

            # Test 9: Logout
            try:
                r = await client.post(f"{self.base_url}/api/v1/auth/logout",
                    headers={"Authorization": f"Bearer {self.access_token}"})
                passed = r.status_code in [200, 204]
                self.log("User Logout", passed, f"status={r.status_code}")
            except Exception as e:
                self.log("User Logout", False, str(e))

            # Test 10: Access after logout (should be 401)
            try:
                r = await client.get(f"{self.base_url}/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {self.access_token}"})
                passed = r.status_code == 401
                self.log("Reject Access After Logout", passed, f"status={r.status_code} (expected 401)")
            except Exception as e:
                self.log("Reject Access After Logout", False, str(e))

        total = len(self.test_results)
        passed_count = sum(1 for r in self.test_results if r["passed"])
        return {
            "suite": "Authentication",
            "total": total,
            "passed": passed_count,
            "failed": total - passed_count,
            "pass_rate": round(passed_count / total * 100, 1) if total else 0,
            "results": self.test_results,
        }


# ============================================================================
# API Endpoint Tests
# ============================================================================

class APIEndpointTestSuite:
    """API endpoint coverage tests"""

    def __init__(self, base_url: str = STAGING_URL):
        self.base_url = base_url
        self.test_results: List[Dict[str, Any]] = []
        self.access_token = None
        self.email = f"staging_api_{int(time.time())}@nested-ai.net"

    def log(self, name: str, passed: bool, details: str = ""):
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} - {name}")
        if details:
            print(f"    Details: {details}")
        self.test_results.append({"name": name, "passed": passed, "details": details})

    async def run(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0, verify=True) as client:

            # Setup: register and login
            try:
                await client.post(f"{self.base_url}/api/v1/auth/register", json={
                    "email": self.email, "password": "ApiTest123!", "name": "API Tester"
                })
                r = await client.post(f"{self.base_url}/api/v1/auth/login", json={
                    "email": self.email, "password": "ApiTest123!"
                })
                self.access_token = r.json().get("access_token")
            except Exception as e:
                self.log("Test Setup", False, f"Could not get auth token: {e}")
                return {"suite": "API Endpoints", "total": 1, "passed": 0, "failed": 1, "pass_rate": 0.0, "results": self.test_results}

            headers = {"Authorization": f"Bearer {self.access_token}"}

            # Test 1: Health endpoint
            try:
                r = await client.get(f"{self.base_url}/health")
                data = r.json()
                passed = r.status_code == 200 and data.get("status") == "ok"
                self.log("GET /health", passed, f"status={r.status_code} version={data.get('version')}")
            except Exception as e:
                self.log("GET /health", False, str(e))

            # Test 2: OpenAPI spec accessible
            try:
                r = await client.get(f"{self.base_url}/openapi.json")
                passed = r.status_code == 200 and "openapi" in r.json()
                self.log("GET /openapi.json", passed, f"status={r.status_code}")
            except Exception as e:
                self.log("GET /openapi.json", False, str(e))

            # Test 3: Auth/me returns correct user
            try:
                r = await client.get(f"{self.base_url}/api/v1/auth/me", headers=headers)
                passed = r.status_code == 200 and r.json().get("email") == self.email
                self.log("GET /api/v1/auth/me", passed, f"status={r.status_code}")
            except Exception as e:
                self.log("GET /api/v1/auth/me", False, str(e))

            # Test 4: Agents endpoint exists and requires auth
            try:
                r_unauth = await client.get(f"{self.base_url}/api/v1/agents")
                r_auth = await client.get(f"{self.base_url}/api/v1/agents", headers=headers)
                passed = r_unauth.status_code == 401 and r_auth.status_code in [200, 404]
                self.log("GET /api/v1/agents (auth required)", passed,
                    f"unauth={r_unauth.status_code} auth={r_auth.status_code}")
            except Exception as e:
                self.log("GET /api/v1/agents (auth required)", False, str(e))

            # Test 5: Missions endpoint
            try:
                r_unauth = await client.get(f"{self.base_url}/api/v1/missions")
                r_auth = await client.get(f"{self.base_url}/api/v1/missions", headers=headers)
                passed = r_unauth.status_code == 401 and r_auth.status_code in [200, 404]
                self.log("GET /api/v1/missions (auth required)", passed,
                    f"unauth={r_unauth.status_code} auth={r_auth.status_code}")
            except Exception as e:
                self.log("GET /api/v1/missions (auth required)", False, str(e))

            # Test 6: Economy balance endpoint
            try:
                r = await client.get(f"{self.base_url}/api/v1/economy/balance", headers=headers)
                passed = r.status_code in [200, 404]
                self.log("GET /api/v1/economy/balance", passed, f"status={r.status_code}")
            except Exception as e:
                self.log("GET /api/v1/economy/balance", False, str(e))

            # Test 7: Rate limiting on auth endpoint
            try:
                # Hit the auth endpoint 12 times rapidly (limit is 10/min)
                statuses = []
                for _ in range(12):
                    r = await client.post(f"{self.base_url}/api/v1/auth/login", json={
                        "email": "nonexistent@test.com", "password": "wrong"
                    })
                    statuses.append(r.status_code)
                rate_limited = 429 in statuses
                self.log("Rate Limiting on Auth Endpoint", rate_limited,
                    f"Got 429 after rapid requests: {rate_limited} | statuses sample: {statuses[-3:]}")
            except Exception as e:
                self.log("Rate Limiting on Auth Endpoint", False, str(e))

            # Test 8: Security headers present
            try:
                r = await client.get(f"{self.base_url}/health")
                hsts = "strict-transport-security" in r.headers
                xframe = "x-frame-options" in r.headers
                xcontent = "x-content-type-options" in r.headers
                passed = hsts and xframe and xcontent
                self.log("Security Headers Present", passed,
                    f"HSTS={hsts} X-Frame={xframe} X-Content-Type={xcontent}")
            except Exception as e:
                self.log("Security Headers Present", False, str(e))

            # Test 9: HTTP redirects to HTTPS
            try:
                r = await client.get("http://nested-ai.net/health",
                    follow_redirects=False)
                passed = r.status_code == 301 and "https" in r.headers.get("location", "")
                self.log("HTTP -> HTTPS Redirect", passed,
                    f"status={r.status_code} location={r.headers.get('location', 'N/A')}")
            except Exception as e:
                self.log("HTTP -> HTTPS Redirect", False, str(e))

            # Test 10: Sensitive paths blocked
            try:
                blocked = []
                for path in ["/.env", "/.git/config", "/admin", "/wp-admin"]:
                    r = await client.get(f"{self.base_url}{path}")
                    blocked.append(r.status_code in [403, 404])
                passed = all(blocked)
                self.log("Sensitive Paths Blocked", passed,
                    f"All {len(blocked)} paths returned 403/404: {passed}")
            except Exception as e:
                self.log("Sensitive Paths Blocked", False, str(e))

        total = len(self.test_results)
        passed_count = sum(1 for r in self.test_results if r["passed"])
        return {
            "suite": "API Endpoints",
            "total": total,
            "passed": passed_count,
            "failed": total - passed_count,
            "pass_rate": round(passed_count / total * 100, 1) if total else 0,
            "results": self.test_results,
        }


# ============================================================================
# Performance Baseline Tests
# ============================================================================

class PerformanceTestSuite:
    """Performance baseline tests"""

    def __init__(self, base_url: str = STAGING_URL):
        self.base_url = base_url
        self.test_results: List[Dict[str, Any]] = []
        self.access_token = None
        self.email = f"staging_perf_{int(time.time())}@nested-ai.net"

    def log(self, name: str, passed: bool, details: str = ""):
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} - {name}")
        if details:
            print(f"    Details: {details}")
        self.test_results.append({"name": name, "passed": passed, "details": details})

    async def run(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0, verify=True) as client:

            # Setup
            try:
                await client.post(f"{self.base_url}/api/v1/auth/register", json={
                    "email": self.email, "password": "PerfTest123!", "name": "Perf Tester"
                })
                r = await client.post(f"{self.base_url}/api/v1/auth/login", json={
                    "email": self.email, "password": "PerfTest123!"
                })
                self.access_token = r.json().get("access_token")
            except Exception as e:
                self.log("Perf Setup", False, str(e))
                return {"suite": "Performance", "total": 1, "passed": 0, "failed": 1, "pass_rate": 0.0, "results": self.test_results}

            headers = {"Authorization": f"Bearer {self.access_token}"}

            # Test 1: Health endpoint response time (target < 200ms)
            try:
                times = []
                for _ in range(10):
                    start = time.time()
                    await client.get(f"{self.base_url}/health")
                    times.append((time.time() - start) * 1000)
                import statistics
                avg_ms = statistics.mean(times)
                p95_ms = sorted(times)[int(len(times) * 0.95)]
                passed = avg_ms < 200
                self.log("Health Endpoint Latency (<200ms avg)", passed,
                    f"avg={avg_ms:.1f}ms p95={p95_ms:.1f}ms over 10 requests")
            except Exception as e:
                self.log("Health Endpoint Latency", False, str(e))

            # Test 2: Auth/me response time (target < 500ms)
            try:
                times = []
                for _ in range(10):
                    start = time.time()
                    await client.get(f"{self.base_url}/api/v1/auth/me", headers=headers)
                    times.append((time.time() - start) * 1000)
                avg_ms = statistics.mean(times)
                passed = avg_ms < 500
                self.log("Auth/me Latency (<500ms avg)", passed,
                    f"avg={avg_ms:.1f}ms over 10 requests")
            except Exception as e:
                self.log("Auth/me Latency", False, str(e))

            # Test 3: Login response time (target < 1000ms — bcrypt is intentionally slow)
            try:
                times = []
                for _ in range(5):
                    start = time.time()
                    await client.post(f"{self.base_url}/api/v1/auth/login", json={
                        "email": self.email, "password": "PerfTest123!"
                    })
                    times.append((time.time() - start) * 1000)
                avg_ms = statistics.mean(times)
                passed = avg_ms < 2000  # bcrypt is slow by design
                self.log("Login Latency (<2000ms avg, bcrypt intentional)", passed,
                    f"avg={avg_ms:.1f}ms over 5 requests")
            except Exception as e:
                self.log("Login Latency", False, str(e))

            # Test 4: Concurrent requests (10 simultaneous health checks)
            try:
                start = time.time()
                tasks = [client.get(f"{self.base_url}/health") for _ in range(10)]
                responses = await asyncio.gather(*tasks, return_exceptions=True)
                elapsed = (time.time() - start) * 1000
                success_count = sum(1 for r in responses if hasattr(r, 'status_code') and r.status_code == 200)
                passed = success_count == 10 and elapsed < 5000
                self.log("10 Concurrent Health Requests", passed,
                    f"success={success_count}/10 total_time={elapsed:.0f}ms")
            except Exception as e:
                self.log("10 Concurrent Health Requests", False, str(e))

            # Test 5: SSL handshake overhead
            try:
                # First request (cold TLS)
                start = time.time()
                await client.get(f"{self.base_url}/health")
                cold_ms = (time.time() - start) * 1000
                # Subsequent requests (warm connection)
                times = []
                for _ in range(5):
                    start = time.time()
                    await client.get(f"{self.base_url}/health")
                    times.append((time.time() - start) * 1000)
                warm_avg = statistics.mean(times)
                passed = warm_avg < 200
                self.log("SSL Connection Reuse (warm < 200ms)", passed,
                    f"cold={cold_ms:.0f}ms warm_avg={warm_avg:.1f}ms")
            except Exception as e:
                self.log("SSL Connection Reuse", False, str(e))

        total = len(self.test_results)
        passed_count = sum(1 for r in self.test_results if r["passed"])
        return {
            "suite": "Performance",
            "total": total,
            "passed": passed_count,
            "failed": total - passed_count,
            "pass_rate": round(passed_count / total * 100, 1) if total else 0,
            "results": self.test_results,
        }


# ============================================================================
# Main Runner
# ============================================================================

async def main():
    print("=" * 70)
    print("CITADEL v5.0 — STAGING TEST SUITE")
    print(f"Target: {STAGING_URL}")
    print(f"Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("Built with Pride for Obex Blackvault")
    print("=" * 70)

    all_results = []

    print("\n[1/3] AUTHENTICATION TESTS")
    print("-" * 40)
    auth_results = await AuthTestSuite().run()
    all_results.append(auth_results)
    print(f"  → {auth_results['passed']}/{auth_results['total']} passed ({auth_results['pass_rate']}%)")

    print("\n[2/3] API ENDPOINT TESTS")
    print("-" * 40)
    api_results = await APIEndpointTestSuite().run()
    all_results.append(api_results)
    print(f"  → {api_results['passed']}/{api_results['total']} passed ({api_results['pass_rate']}%)")

    print("\n[3/3] PERFORMANCE BASELINE TESTS")
    print("-" * 40)
    perf_results = await PerformanceTestSuite().run()
    all_results.append(perf_results)
    print(f"  → {perf_results['passed']}/{perf_results['total']} passed ({perf_results['pass_rate']}%)")

    # Summary
    total_tests = sum(r["total"] for r in all_results)
    total_passed = sum(r["passed"] for r in all_results)
    total_failed = total_tests - total_passed
    overall_rate = round(total_passed / total_tests * 100, 1) if total_tests else 0

    print("\n" + "=" * 70)
    print("OVERALL RESULTS")
    print("=" * 70)
    for r in all_results:
        bar = "✅" if r["pass_rate"] >= 80 else "⚠️" if r["pass_rate"] >= 60 else "❌"
        print(f"  {bar} {r['suite']:25s} {r['passed']:2d}/{r['total']:2d}  ({r['pass_rate']}%)")
    print("-" * 70)
    print(f"  {'TOTAL':25s} {total_passed:2d}/{total_tests:2d}  ({overall_rate}%)")
    print("=" * 70)

    if total_failed > 0:
        print("\nFAILED TESTS:")
        for suite in all_results:
            for r in suite["results"]:
                if not r["passed"]:
                    print(f"  ❌ [{suite['suite']}] {r['name']}: {r['details']}")

    # Save results
    report = {
        "timestamp": datetime.now().isoformat(),
        "target": STAGING_URL,
        "total_tests": total_tests,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "overall_pass_rate": overall_rate,
        "suites": all_results,
    }
    report_path = "/home/ubuntu/citadel_staging_test_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n📄 Full report saved to: {report_path}")

    return overall_rate >= 80


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
