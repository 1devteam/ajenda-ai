"""
Performance Baseline Test Suite for Omnipath v5.0
Tests API response times, database performance, and load handling

Built with Pride for Obex Blackvault
"""

import asyncio
import httpx
import time
import statistics
import json
from typing import List, Dict, Any
from datetime import datetime
import concurrent.futures


class PerformanceTest:
    """Performance testing suite"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results = {"timestamp": datetime.now().isoformat(), "tests": []}
        self.access_token = None
        self.test_user_email = f"perf_test_{int(time.time())}@example.com"

    async def setup(self):
        """Setup: Create test user and get auth token"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Register user
            user_data = {
                "email": self.test_user_email,
                "password": "PerfTest123!",
                "full_name": "Performance Test User",
            }
            await client.post(f"{self.base_url}/api/v1/auth/register", json=user_data)

            # Login
            login_data = {"username": self.test_user_email, "password": "PerfTest123!"}
            response = await client.post(
                f"{self.base_url}/api/v1/auth/login", json=login_data
            )
            if response.status_code == 200:
                self.access_token = response.json().get("access_token")

    def log_test(self, name: str, metrics: Dict[str, Any]):
        """Log test results"""
        result = {"name": name, "timestamp": datetime.now().isoformat(), **metrics}
        self.results["tests"].append(result)

        print(f"\n{'='*60}")
        print(f"Test: {name}")
        print(f"{'='*60}")
        for key, value in metrics.items():
            if isinstance(value, float):
                print(f"  {key}: {value:.2f}")
            else:
                print(f"  {key}: {value}")

    async def test_health_check_latency(self):
        """Test 1: Health check endpoint latency"""
        print("\n🔍 Testing health check latency...")

        latencies = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for _ in range(100):
                start = time.time()
                response = await client.get(f"{self.base_url}/health")
                latency = (time.time() - start) * 1000  # Convert to ms
                latencies.append(latency)

                if response.status_code != 200:
                    print(f"  ⚠️  Health check failed: {response.status_code}")

        self.log_test(
            "Health Check Latency",
            {
                "mean_ms": statistics.mean(latencies),
                "median_ms": statistics.median(latencies),
                "p95_ms": statistics.quantiles(latencies, n=20)[18],  # 95th percentile
                "p99_ms": statistics.quantiles(latencies, n=100)[98],  # 99th percentile
                "min_ms": min(latencies),
                "max_ms": max(latencies),
                "samples": len(latencies),
                "target_ms": 200,
                "passed": statistics.quantiles(latencies, n=20)[18] < 200,
            },
        )

    async def test_api_response_times(self):
        """Test 2: API endpoint response times"""
        print("\n🔍 Testing API endpoint response times...")

        if not self.access_token:
            print("  ⚠️  No auth token, skipping")
            return

        headers = {"Authorization": f"Bearer {self.access_token}"}
        endpoints = [
            ("GET", "/api/v1/agents"),
            ("GET", "/api/v1/missions"),
            ("GET", "/api/v1/auth/me"),
        ]

        results = {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            for method, endpoint in endpoints:
                latencies = []
                for _ in range(50):
                    start = time.time()
                    if method == "GET":
                        response = await client.get(
                            f"{self.base_url}{endpoint}", headers=headers
                        )
                    latency = (time.time() - start) * 1000
                    latencies.append(latency)

                results[endpoint] = {
                    "mean_ms": statistics.mean(latencies),
                    "p95_ms": statistics.quantiles(latencies, n=20)[18],
                    "samples": len(latencies),
                }

        self.log_test(
            "API Response Times",
            {
                "endpoints_tested": len(endpoints),
                "results": results,
                "target_p95_ms": 500,
                "passed": all(r["p95_ms"] < 500 for r in results.values()),
            },
        )

    async def test_concurrent_requests(self):
        """Test 3: Concurrent request handling"""
        print("\n🔍 Testing concurrent request handling (100 requests)...")

        if not self.access_token:
            print("  ⚠️  No auth token, skipping")
            return

        headers = {"Authorization": f"Bearer {self.access_token}"}

        async def make_request(client):
            try:
                start = time.time()
                response = await client.get(
                    f"{self.base_url}/api/v1/agents", headers=headers
                )
                latency = (time.time() - start) * 1000
                return {
                    "latency_ms": latency,
                    "status": response.status_code,
                    "success": response.status_code == 200,
                }
            except Exception as e:
                return {"latency_ms": 0, "status": 0, "success": False, "error": str(e)}

        start_time = time.time()
        # Use connection limits to avoid overwhelming the server
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
        async with httpx.AsyncClient(timeout=120.0, limits=limits) as client:
            tasks = [make_request(client) for _ in range(100)]
            results = await asyncio.gather(*tasks)

        total_time = time.time() - start_time
        latencies = [r["latency_ms"] for r in results]
        successes = sum(1 for r in results if r["success"])

        self.log_test(
            "Concurrent Request Handling",
            {
                "total_requests": 100,
                "successful_requests": successes,
                "failed_requests": 100 - successes,
                "total_time_seconds": total_time,
                "requests_per_second": 100 / total_time,
                "mean_latency_ms": statistics.mean(latencies),
                "p95_latency_ms": statistics.quantiles(latencies, n=20)[18],
                "p99_latency_ms": statistics.quantiles(latencies, n=100)[98],
                "target_success_rate": 0.95,
                "actual_success_rate": successes / 100,
                "passed": (successes / 100) >= 0.95,
            },
        )

    async def test_mission_execution_time(self):
        """Test 4: Mission execution performance"""
        print("\n🔍 Testing mission execution time...")

        if not self.access_token:
            print("  ⚠️  No auth token, skipping")
            return

        headers = {"Authorization": f"Bearer {self.access_token}"}

        # Create test agent
        async with httpx.AsyncClient(timeout=30.0) as client:
            agent_data = {"name": "Performance Test Agent", "type": "commander"}
            response = await client.post(
                f"{self.base_url}/api/v1/agents", json=agent_data, headers=headers
            )

            if response.status_code not in [200, 201]:
                print(f"  ⚠️  Failed to create agent: {response.status_code}")
                return

            agent_id = response.json().get("id")

            # Execute mission and measure time
            mission_data = {"agent_id": agent_id, "objective": "Say hello"}

            start = time.time()
            response = await client.post(
                f"{self.base_url}/api/v1/missions", json=mission_data, headers=headers
            )

            if response.status_code not in [200, 201]:
                print(f"  ⚠️  Failed to create mission: {response.status_code}")
                return

            mission_id = response.json().get("id")

            # Poll for completion
            max_wait = 30  # seconds
            poll_interval = 0.5
            elapsed = 0
            completed = False

            while elapsed < max_wait:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                response = await client.get(
                    f"{self.base_url}/api/v1/missions/{mission_id}", headers=headers
                )

                if response.status_code == 200:
                    status = response.json().get("status")
                    if status in ["COMPLETED", "FAILED"]:
                        completed = True
                        execution_time = response.json().get("execution_time", elapsed)
                        break

            total_time = time.time() - start

            self.log_test(
                "Mission Execution Time",
                {
                    "mission_id": mission_id,
                    "completed": completed,
                    "total_time_seconds": total_time,
                    "execution_time_seconds": execution_time if completed else None,
                    "target_seconds": 10,
                    "passed": completed and total_time < 10,
                },
            )

    async def test_database_query_performance(self):
        """Test 5: Database query performance (indirect via API)"""
        print("\n🔍 Testing database query performance...")

        if not self.access_token:
            print("  ⚠️  No auth token, skipping")
            return

        headers = {"Authorization": f"Bearer {self.access_token}"}

        # Create multiple agents to test list query
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Create 10 agents
            for i in range(10):
                agent_data = {"name": f"DB Test Agent {i}", "type": "commander"}
                await client.post(
                    f"{self.base_url}/api/v1/agents", json=agent_data, headers=headers
                )

            # Measure list query performance
            latencies = []
            for _ in range(20):
                start = time.time()
                response = await client.get(
                    f"{self.base_url}/api/v1/agents", headers=headers
                )
                latency = (time.time() - start) * 1000
                latencies.append(latency)

            self.log_test(
                "Database Query Performance",
                {
                    "query_type": "List agents (10+ records)",
                    "mean_latency_ms": statistics.mean(latencies),
                    "p95_latency_ms": statistics.quantiles(latencies, n=20)[18],
                    "samples": len(latencies),
                    "target_ms": 50,
                    "passed": statistics.quantiles(latencies, n=20)[18] < 50,
                },
            )

    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 60)
        print("PERFORMANCE TEST SUMMARY")
        print("=" * 60)

        total = len(self.results["tests"])
        passed = sum(1 for t in self.results["tests"] if t.get("passed", False))

        print(f"Total Tests: {total}")
        print(f"Passed: {passed} ✅")
        print(f"Failed: {total - passed} ❌")
        print("=" * 60)

        return passed == total

    def save_results(self, filename: str = "performance_baseline.json"):
        """Save results to JSON file"""
        with open(filename, "w") as f:
            json.dump(self.results, f, indent=2)
        print(f"\n📄 Results saved to {filename}")


async def run_all_tests():
    """Run all performance tests"""
    print("=" * 60)
    print("OMNIPATH V5.0 - PERFORMANCE BASELINE TEST")
    print("Built with Pride for Obex Blackvault")
    print("=" * 60)

    tester = PerformanceTest()

    # Setup
    print("\n🔧 Setting up test environment...")
    await tester.setup()

    # Run tests
    await tester.test_health_check_latency()
    await tester.test_api_response_times()
    await tester.test_database_query_performance()
    await tester.test_concurrent_requests()
    await tester.test_mission_execution_time()

    # Summary
    success = tester.print_summary()
    tester.save_results()

    return success


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)
