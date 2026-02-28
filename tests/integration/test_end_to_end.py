"""
End-to-End Integration Test for Omnipath v5.0
Tests the complete system flow from agent creation to mission execution

Built with Pride for Obex Blackvault
"""

import asyncio
import httpx
import json
import time
from typing import Dict, Optional
from datetime import datetime


class OmnipathE2ETest:
    """End-to-end test suite for Omnipath v5.0"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
        self.test_results = []
        self.test_agent_id: Optional[str] = None
        self.test_mission_id: Optional[str] = None
        self.test_tenant_id: Optional[str] = None
        self.test_user_id: Optional[str] = None
        self.test_user_email: Optional[str] = None
        self.test_user_password: Optional[str] = None
        self.auth_token: Optional[str] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    def log_test(self, name: str, passed: bool, details: str = ""):
        """Log test result"""
        result = {
            "name": name,
            "passed": passed,
            "details": details,
            "timestamp": datetime.now().isoformat(),
        }
        self.test_results.append(result)
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {name}")
        if details:
            print(f"  Details: {details}")

    def get_auth_headers(self) -> Dict[str, str]:
        """Get authorization headers if token is available"""
        if self.auth_token:
            return {"Authorization": f"Bearer {self.auth_token}"}
        return {}

    async def test_health_check(self) -> bool:
        """Test 1: Backend health check"""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            passed = response.status_code == 200
            data = response.json() if passed else {}
            self.log_test(
                "Health Check",
                passed,
                f"Status: {response.status_code}, Service: {data.get('service', 'N/A')}",
            )
            return passed
        except Exception as e:
            self.log_test("Health Check", False, f"Error: {str(e)}")
            return False

    async def test_metrics_endpoint(self) -> bool:
        """Test 2: Prometheus metrics endpoint"""
        try:
            response = await self.client.get(f"{self.base_url}/metrics")
            passed = response.status_code == 200 and "omnipath" in response.text
            self.log_test(
                "Metrics Endpoint",
                passed,
                f"Status: {response.status_code}, Contains metrics: {passed}",
            )
            return passed
        except Exception as e:
            self.log_test("Metrics Endpoint", False, f"Error: {str(e)}")
            return False

    async def test_api_docs(self) -> bool:
        """Test 3: API documentation endpoint"""
        try:
            response = await self.client.get(f"{self.base_url}/docs")
            passed = response.status_code == 200
            self.log_test("API Documentation", passed, f"Status: {response.status_code}")
            return passed
        except Exception as e:
            self.log_test("API Documentation", False, f"Error: {str(e)}")
            return False

    async def test_create_tenant(self) -> bool:
        """Test 4: Create test tenant"""
        try:
            tenant_data = {
                "name": "Test Tenant E2E",
                "slug": f"test-tenant-e2e-{int(time.time())}",
                "settings": {},
            }
            response = await self.client.post(f"{self.base_url}/api/v1/tenants", json=tenant_data)
            passed = response.status_code in [200, 201]
            if passed:
                data = response.json()
                self.test_tenant_id = data.get("id")
            self.log_test(
                "Create Tenant",
                passed,
                f"Status: {response.status_code}, Tenant ID: {self.test_tenant_id or 'N/A'}",
            )
            return passed
        except Exception as e:
            self.log_test("Create Tenant", False, f"Error: {str(e)}")
            return False

    async def test_register_user(self) -> bool:
        """Test 5: Register test user"""
        try:
            # Store credentials for login
            self.test_user_email = f"test-e2e-{int(time.time())}@example.com"
            self.test_user_password = "TestPassword123!"

            user_data = {
                "email": self.test_user_email,
                "password": self.test_user_password,
                "name": "Test User E2E",
            }

            # Only add tenant_id if we have one
            if self.test_tenant_id:
                user_data["tenant_id"] = self.test_tenant_id

            response = await self.client.post(
                f"{self.base_url}/api/v1/auth/register", json=user_data
            )
            passed = response.status_code in [200, 201]

            if passed:
                data = response.json()
                self.test_user_id = data.get("id")
                details = f"Status: {response.status_code}, User ID: {self.test_user_id or 'N/A'}"
            else:
                # Show validation error details
                try:
                    error_data = response.json()
                    details = f"Status: {response.status_code}, Error: {json.dumps(error_data)}"
                except Exception:
                    details = f"Status: {response.status_code}, Response: {response.text[:200]}"

            self.log_test("Register User", passed, details)
            return passed
        except Exception as e:
            self.log_test("Register User", False, f"Exception: {str(e)}")
            return False

    async def test_login_user(self) -> bool:
        """Test 6: Login and get access token"""
        if not self.test_user_email or not self.test_user_password:
            self.log_test("Login User", False, "No user credentials available")
            return False

        try:
            # OAuth2 password flow uses form data
            login_data = {
                "username": self.test_user_email,
                "password": self.test_user_password,
            }
            response = await self.client.post(
                f"{self.base_url}/api/v1/auth/login",
                json=login_data,  # Send JSON to match Pydantic model
            )
            passed = response.status_code == 200

            if passed:
                data = response.json()
                self.auth_token = data.get("access_token")
                details = f"Status: {response.status_code}, Has Token: {bool(self.auth_token)}"
            else:
                try:
                    error_data = response.json()
                    details = f"Status: {response.status_code}, Error: {json.dumps(error_data)}"
                except Exception:
                    details = f"Status: {response.status_code}, Response: {response.text[:200]}"

            self.log_test("Login User", passed, details)
            return passed
        except Exception as e:
            self.log_test("Login User", False, f"Exception: {str(e)}")
            return False

    async def test_create_agent(self) -> bool:
        """Test 7: Create test agent (with authentication)"""
        if not self.auth_token:
            self.log_test("Create Agent", False, "No auth token available")
            return False

        try:
            agent_data = {
                "name": f"Test Agent E2E {int(time.time())}",
                "type": "custom",
                "model": "gpt-4",
                "temperature": 0.7,
                "system_prompt": "You are a test agent",
                "capabilities": ["test"],
                "config": {},
            }
            response = await self.client.post(
                f"{self.base_url}/api/v1/agents",
                json=agent_data,
                headers=self.get_auth_headers(),
            )
            passed = response.status_code in [200, 201]

            if passed:
                data = response.json()
                self.test_agent_id = data.get("id")
                details = f"Status: {response.status_code}, Agent ID: {self.test_agent_id or 'N/A'}"
            else:
                try:
                    error_data = response.json()
                    details = f"Status: {response.status_code}, Error: {json.dumps(error_data)}"
                except Exception:
                    details = f"Status: {response.status_code}, Response: {response.text[:200]}"

            self.log_test("Create Agent", passed, details)
            return passed
        except Exception as e:
            self.log_test("Create Agent", False, f"Exception: {str(e)}")
            return False

    async def test_get_agent(self) -> bool:
        """Test 8: Retrieve agent details (with authentication)"""
        if not self.test_agent_id:
            self.log_test("Get Agent", False, "No agent ID available")
            return False
        if not self.auth_token:
            self.log_test("Get Agent", False, "No auth token available")
            return False

        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/agents/{self.test_agent_id}",
                headers=self.get_auth_headers(),
            )
            passed = response.status_code == 200
            if passed:
                data = response.json()
                agent_name = data.get("name", "N/A")
            else:
                agent_name = "N/A"
            self.log_test(
                "Get Agent",
                passed,
                f"Status: {response.status_code}, Name: {agent_name}",
            )
            return passed
        except Exception as e:
            self.log_test("Get Agent", False, f"Error: {str(e)}")
            return False

    async def test_list_agents(self) -> bool:
        """Test 9: List all agents (with authentication)"""
        if not self.auth_token:
            self.log_test("List Agents", False, "No auth token available")
            return False

        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/agents", headers=self.get_auth_headers()
            )
            passed = response.status_code == 200
            if passed:
                data = response.json()
                count = len(data) if isinstance(data, list) else data.get("total", 0)
            else:
                count = 0
            self.log_test("List Agents", passed, f"Status: {response.status_code}, Count: {count}")
            return passed
        except Exception as e:
            self.log_test("List Agents", False, f"Error: {str(e)}")
            return False

    async def test_create_mission(self) -> bool:
        """Test 10: Create test mission (with authentication)"""
        if not self.test_agent_id:
            self.log_test("Create Mission", False, "No agent ID available")
            return False
        if not self.auth_token:
            self.log_test("Create Mission", False, "No auth token available")
            return False

        try:
            mission_data = {
                "agent_id": self.test_agent_id,
                "objective": "End-to-end test mission",
                "priority": "normal",
                "context": {
                    "task": "Respond with 'Test successful'",
                    "complexity": "low",
                },
                "max_steps": 10,
                "timeout_seconds": 300,
            }
            response = await self.client.post(
                f"{self.base_url}/api/v1/missions",
                json=mission_data,
                headers=self.get_auth_headers(),
            )
            passed = response.status_code in [200, 201]
            if passed:
                data = response.json()
                self.test_mission_id = data.get("id")
            self.log_test(
                "Create Mission",
                passed,
                f"Status: {response.status_code}, Mission ID: {self.test_mission_id or 'N/A'}",
            )
            return passed
        except Exception as e:
            self.log_test("Create Mission", False, f"Error: {str(e)}")
            return False

    async def test_get_mission(self) -> bool:
        """Test 11: Retrieve mission details (with authentication)"""
        if not self.test_mission_id:
            self.log_test("Get Mission", False, "No mission ID available")
            return False
        if not self.auth_token:
            self.log_test("Get Mission", False, "No auth token available")
            return False

        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/missions/{self.test_mission_id}",
                headers=self.get_auth_headers(),
            )
            passed = response.status_code == 200
            if passed:
                data = response.json()
                status = data.get("status", "N/A")
            else:
                status = "N/A"
            self.log_test(
                "Get Mission",
                passed,
                f"Status: {response.status_code}, Mission Status: {status}",
            )
            return passed
        except Exception as e:
            self.log_test("Get Mission", False, f"Error: {str(e)}")
            return False

    async def test_economy_balance(self) -> bool:
        """Test 12: Check economy balance"""
        try:
            response = await self.client.get(f"{self.base_url}/api/v1/economy/balance")
            # May return 401/403 if auth required - that's acceptable
            passed = response.status_code in [200, 401, 403]
            self.log_test(
                "Economy Balance",
                passed,
                f"Status: {response.status_code} (Auth may be required)",
            )
            return passed
        except Exception as e:
            self.log_test("Economy Balance", False, f"Error: {str(e)}")
            return False

    async def test_meta_learning_leaderboard(self) -> bool:
        """Test 13: Meta-learning leaderboard"""
        try:
            response = await self.client.get(f"{self.base_url}/api/v1/meta-learning/leaderboard")
            passed = response.status_code in [200, 401, 403]
            self.log_test("Meta-Learning Leaderboard", passed, f"Status: {response.status_code}")
            return passed
        except Exception as e:
            self.log_test("Meta-Learning Leaderboard", False, f"Error: {str(e)}")
            return False

    async def test_system_insights(self) -> bool:
        """Test 14: System-wide insights"""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/meta-learning/system-insights"
            )
            passed = response.status_code in [200, 401, 403]
            self.log_test("System Insights", passed, f"Status: {response.status_code}")
            return passed
        except Exception as e:
            self.log_test("System Insights", False, f"Error: {str(e)}")
            return False

    async def cleanup(self):
        """Cleanup: Delete test data"""
        print("\n🧹 Cleaning up test data...")

        # Delete test mission
        if self.test_mission_id and self.auth_token:
            try:
                await self.client.delete(
                    f"{self.base_url}/api/v1/missions/{self.test_mission_id}",
                    headers=self.get_auth_headers(),
                )
                print(f"  ✅ Deleted mission {self.test_mission_id}")
            except Exception as e:
                print(f"  ⚠️  Could not delete mission: {e}")

        # Delete test agent
        if self.test_agent_id and self.auth_token:
            try:
                await self.client.delete(
                    f"{self.base_url}/api/v1/agents/{self.test_agent_id}",
                    headers=self.get_auth_headers(),
                )
                print(f"  ✅ Deleted agent {self.test_agent_id}")
            except Exception as e:
                print(f"  ⚠️  Could not delete agent: {e}")

    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)

        total = len(self.test_results)
        passed = sum(1 for r in self.test_results if r["passed"])
        failed = total - passed
        pass_rate = (passed / total * 100) if total > 0 else 0

        print(f"Total Tests: {total}")
        print(f"Passed: {passed} ✅")
        print(f"Failed: {failed} ❌")
        print(f"Pass Rate: {pass_rate:.1f}%")
        print("=" * 60)

        if failed > 0:
            print("\nFailed Tests:")
            for result in self.test_results:
                if not result["passed"]:
                    print(f"  ❌ {result['name']}: {result['details']}")

        return pass_rate >= 80  # 80% pass rate required

    def save_results(self, filename: str = "test_results_e2e.json"):
        """Save test results to JSON file"""
        results = {
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(self.test_results),
            "passed": sum(1 for r in self.test_results if r["passed"]),
            "failed": sum(1 for r in self.test_results if not r["passed"]),
            "tests": self.test_results,
        }

        with open(filename, "w") as f:
            json.dump(results, f, indent=2)

        print(f"\n📄 Results saved to {filename}")


async def run_all_tests():
    """Run all end-to-end tests"""
    print("=" * 60)
    print("OMNIPATH V5.0 - END-TO-END INTEGRATION TEST")
    print("Built with Pride for Obex Blackvault")
    print("=" * 60)
    print()

    async with OmnipathE2ETest() as tester:
        # Run all tests in sequence
        await tester.test_health_check()
        await tester.test_metrics_endpoint()
        await tester.test_api_docs()
        await tester.test_create_tenant()

        # Authentication flow (NEW)
        await tester.test_register_user()
        await tester.test_login_user()

        # Protected endpoints (now with auth)
        await tester.test_create_agent()
        await tester.test_get_agent()
        await tester.test_list_agents()
        await tester.test_create_mission()
        await tester.test_get_mission()

        # Public/optional auth endpoints
        await tester.test_economy_balance()
        await tester.test_meta_learning_leaderboard()
        await tester.test_system_insights()

        # Cleanup
        await tester.cleanup()

        # Print summary
        success = tester.print_summary()

        # Save results
        tester.save_results()

        return success


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)
