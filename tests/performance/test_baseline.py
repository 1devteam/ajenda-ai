"""
Performance Baseline Test for Omnipath v5.0
Establishes performance baselines for API endpoints

Built with Pride for Obex Blackvault
"""

import asyncio
import httpx
import json
import time
import statistics
from typing import List, Dict, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor


class OmnipathPerformanceTest:
    """Performance baseline test suite"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.test_results = {}
        
    def log_metric(self, name: str, metrics: Dict[str, Any]):
        """Log performance metric"""
        self.test_results[name] = metrics
        print(f"\n📊 {name}")
        print(f"  Min: {metrics['min']:.0f}ms")
        print(f"  Max: {metrics['max']:.0f}ms")
        print(f"  Mean: {metrics['mean']:.0f}ms")
        print(f"  Median: {metrics['median']:.0f}ms")
        print(f"  P95: {metrics['p95']:.0f}ms")
        print(f"  P99: {metrics['p99']:.0f}ms")
        
        # Check against targets
        if metrics['p95'] < metrics.get('target_p95', float('inf')):
            print(f"  ✅ P95 within target ({metrics.get('target_p95')}ms)")
        else:
            print(f"  ❌ P95 exceeds target ({metrics.get('target_p95')}ms)")
    
    async def measure_endpoint(
        self,
        method: str,
        endpoint: str,
        iterations: int = 100,
        target_p95: float = 200.0
    ) -> Dict[str, Any]:
        """Measure endpoint performance"""
        latencies = []
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(iterations):
                start = time.time()
                try:
                    if method == "GET":
                        response = await client.get(f"{self.base_url}{endpoint}")
                    elif method == "POST":
                        response = await client.post(f"{self.base_url}{endpoint}")
                    
                    latency = (time.time() - start) * 1000  # Convert to ms
                    if response.status_code < 500:  # Count non-server errors
                        latencies.append(latency)
                except Exception as e:
                    print(f"  ⚠️  Request {i+1} failed: {e}")
        
        if not latencies:
            return {
                "error": "All requests failed",
                "iterations": iterations
            }
        
        latencies.sort()
        
        return {
            "iterations": len(latencies),
            "min": min(latencies),
            "max": max(latencies),
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "p95": latencies[int(len(latencies) * 0.95)],
            "p99": latencies[int(len(latencies) * 0.99)],
            "target_p95": target_p95
        }
    
    async def test_health_endpoint(self):
        """Test 1: Health endpoint performance"""
        print("\n🔍 Testing health endpoint...")
        metrics = await self.measure_endpoint("GET", "/health", iterations=100, target_p95=50.0)
        self.log_metric("Health Endpoint", metrics)
    
    async def test_metrics_endpoint(self):
        """Test 2: Metrics endpoint performance"""
        print("\n🔍 Testing metrics endpoint...")
        metrics = await self.measure_endpoint("GET", "/metrics", iterations=50, target_p95=100.0)
        self.log_metric("Metrics Endpoint", metrics)
    
    async def test_list_agents(self):
        """Test 3: List agents performance"""
        print("\n🔍 Testing list agents endpoint...")
        metrics = await self.measure_endpoint("GET", "/api/v1/agents", iterations=50, target_p95=200.0)
        self.log_metric("List Agents", metrics)
    
    async def test_concurrent_requests(self, concurrent_users: int = 10):
        """Test 4: Concurrent request handling"""
        print(f"\n🔍 Testing concurrent requests ({concurrent_users} users)...")
        
        async def make_request():
            async with httpx.AsyncClient(timeout=30.0) as client:
                start = time.time()
                try:
                    response = await client.get(f"{self.base_url}/health")
                    latency = (time.time() - start) * 1000
                    return latency if response.status_code == 200 else None
                except:
                    return None
        
        # Run concurrent requests
        tasks = [make_request() for _ in range(concurrent_users)]
        latencies = await asyncio.gather(*tasks)
        latencies = [l for l in latencies if l is not None]
        
        if not latencies:
            print("  ❌ All concurrent requests failed")
            return
        
        latencies.sort()
        
        metrics = {
            "concurrent_users": concurrent_users,
            "successful_requests": len(latencies),
            "min": min(latencies),
            "max": max(latencies),
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "p95": latencies[int(len(latencies) * 0.95)] if len(latencies) > 20 else max(latencies),
            "p99": latencies[int(len(latencies) * 0.99)] if len(latencies) > 100 else max(latencies),
            "target_p95": 500.0
        }
        
        self.log_metric(f"Concurrent Requests ({concurrent_users} users)", metrics)
    
    async def test_throughput(self, duration_seconds: int = 10):
        """Test 5: System throughput"""
        print(f"\n🔍 Testing throughput ({duration_seconds}s)...")
        
        request_count = 0
        error_count = 0
        start_time = time.time()
        end_time = start_time + duration_seconds
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            while time.time() < end_time:
                try:
                    response = await client.get(f"{self.base_url}/health")
                    if response.status_code == 200:
                        request_count += 1
                    else:
                        error_count += 1
                except:
                    error_count += 1
        
        actual_duration = time.time() - start_time
        throughput = request_count / actual_duration
        error_rate = error_count / (request_count + error_count) * 100 if (request_count + error_count) > 0 else 0
        
        print(f"\n📊 Throughput Test")
        print(f"  Duration: {actual_duration:.1f}s")
        print(f"  Successful Requests: {request_count}")
        print(f"  Failed Requests: {error_count}")
        print(f"  Throughput: {throughput:.1f} req/sec")
        print(f"  Error Rate: {error_rate:.2f}%")
        
        if throughput >= 50:
            print(f"  ✅ Throughput meets target (50 req/sec)")
        else:
            print(f"  ❌ Throughput below target (50 req/sec)")
        
        self.test_results["Throughput"] = {
            "duration": actual_duration,
            "successful_requests": request_count,
            "failed_requests": error_count,
            "throughput_req_per_sec": throughput,
            "error_rate_percent": error_rate,
            "target_throughput": 50.0
        }
    
    def print_summary(self):
        """Print performance summary"""
        print("\n" + "="*60)
        print("PERFORMANCE BASELINE SUMMARY")
        print("="*60)
        
        targets_met = 0
        targets_total = 0
        
        for name, metrics in self.test_results.items():
            if "error" in metrics:
                print(f"\n❌ {name}: {metrics['error']}")
                continue
            
            if "p95" in metrics and "target_p95" in metrics:
                targets_total += 1
                if metrics["p95"] < metrics["target_p95"]:
                    targets_met += 1
                    status = "✅"
                else:
                    status = "❌"
                print(f"\n{status} {name}")
                print(f"   P95: {metrics['p95']:.0f}ms (Target: {metrics['target_p95']:.0f}ms)")
            
            if "throughput_req_per_sec" in metrics:
                targets_total += 1
                if metrics["throughput_req_per_sec"] >= metrics.get("target_throughput", 0):
                    targets_met += 1
                    status = "✅"
                else:
                    status = "❌"
                print(f"\n{status} Throughput")
                print(f"   {metrics['throughput_req_per_sec']:.1f} req/sec (Target: {metrics.get('target_throughput', 0):.0f})")
        
        print("\n" + "="*60)
        print(f"Targets Met: {targets_met}/{targets_total}")
        print("="*60)
        
        return targets_met == targets_total
    
    def save_results(self, filename: str = "test_results_performance.json"):
        """Save test results to JSON file"""
        results = {
            "timestamp": datetime.now().isoformat(),
            "tests": self.test_results
        }
        
        with open(filename, "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n📄 Results saved to {filename}")


async def run_all_tests():
    """Run all performance tests"""
    print("="*60)
    print("OMNIPATH V5.0 - PERFORMANCE BASELINE TEST")
    print("Built with Pride for Obex Blackvault")
    print("="*60)
    print("\n⚠️  Note: Ensure backend is running and warmed up")
    print("   Run a few manual requests first to warm up the system")
    
    tester = OmnipathPerformanceTest()
    
    # Run all tests
    await tester.test_health_endpoint()
    await tester.test_metrics_endpoint()
    await tester.test_list_agents()
    await tester.test_concurrent_requests(concurrent_users=10)
    await tester.test_concurrent_requests(concurrent_users=50)
    await tester.test_concurrent_requests(concurrent_users=100)
    await tester.test_throughput(duration_seconds=10)
    
    # Print summary
    success = tester.print_summary()
    
    # Save results
    tester.save_results()
    
    return success


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)
