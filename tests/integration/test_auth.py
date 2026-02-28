"""
Authentication & Authorization Integration Test for Omnipath v5.0
Tests JWT authentication, RBAC, and multi-tenancy

Built with Pride for Obex Blackvault
"""

import asyncio
import httpx
import json
import time
from typing import Dict, Any, Optional
from datetime import datetime, timedelta


class OmnipathAuthTest:
    """Authentication and authorization test suite"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
        self.test_results = []
        self.test_user_email = f"test_user_{int(time.time())}@example.com"
        self.test_user_password = "TestPassword123!"
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.test_tenant_id: Optional[str] = None
        self.test_user_id: Optional[str] = None

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

    async def test_register_user(self) -> bool:
        """Test 1: User registration"""
        try:
            user_data = {
                "email": self.test_user_email,
                "password": self.test_user_password,
                "full_name": "Test User E2E",
            }
            response = await self.client.post(
                f"{self.base_url}/api/v1/auth/register", json=user_data
            )
            passed = response.status_code in [200, 201]
            if passed:
                data = response.json()
                self.test_user_id = data.get("id") or data.get("user_id")
                self.test_tenant_id = data.get("tenant_id")
            self.log_test(
                "User Registration",
                passed,
                f"Status: {response.status_code}, User ID: {self.test_user_id or 'N/A'}",
            )
            return passed
        except Exception as e:
            self.log_test("User Registration", False, f"Error: {str(e)}")
            return False

    async def test_login(self) -> bool:
        """Test 2: User login"""
        try:
            login_data = {
                "username": self.test_user_email,  # OAuth2 uses 'username' field
                "password": self.test_user_password,
            }
            response = await self.client.post(
                f"{self.base_url}/api/v1/auth/login",
                json=login_data,  # Send JSON to match Pydantic model
            )
            passed = response.status_code == 200
            if passed:
                data = response.json()
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                token_type = data.get("token_type", "bearer")
            else:
                token_type = "N/A"
            self.log_test(
                "User Login",
                passed,
                f"Status: {response.status_code}, Token Type: {token_type}, Has Token: {bool(self.access_token)}",
            )
            return passed
        except Exception as e:
            self.log_test("User Login", False, f"Error: {str(e)}")
            return False

    async def test_access_protected_endpoint(self) -> bool:
        """Test 3: Access protected endpoint with token"""
        if not self.access_token:
            self.log_test(
                "Access Protected Endpoint", False, "No access token available"
            )
            return False

        try:
            headers = {"Authorization": f"Bearer {self.access_token}"}
            response = await self.client.get(
                f"{self.base_url}/api/v1/agents", headers=headers
            )
            passed = response.status_code == 200
            self.log_test(
                "Access Protected Endpoint", passed, f"Status: {response.status_code}"
            )
            return passed
        except Exception as e:
            self.log_test("Access Protected Endpoint", False, f"Error: {str(e)}")
            return False

    async def test_access_without_token(self) -> bool:
        """Test 4: Access protected endpoint without token (should fail)"""
        try:
            response = await self.client.get(f"{self.base_url}/api/v1/agents")
            # Should return 401 or 403
            passed = response.status_code in [401, 403]
            self.log_test(
                "Access Without Token (Should Fail)",
                passed,
                f"Status: {response.status_code} (Expected 401/403)",
            )
            return passed
        except Exception as e:
            self.log_test("Access Without Token", False, f"Error: {str(e)}")
            return False

    async def test_access_with_invalid_token(self) -> bool:
        """Test 5: Access with invalid token (should fail)"""
        try:
            headers = {"Authorization": "Bearer invalid_token_12345"}
            response = await self.client.get(
                f"{self.base_url}/api/v1/agents", headers=headers
            )
            # Should return 401 or 403
            passed = response.status_code in [401, 403]
            self.log_test(
                "Access With Invalid Token (Should Fail)",
                passed,
                f"Status: {response.status_code} (Expected 401/403)",
            )
            return passed
        except Exception as e:
            self.log_test("Access With Invalid Token", False, f"Error: {str(e)}")
            return False

    async def test_refresh_token(self) -> bool:
        """Test 6: Refresh access token"""
        if not self.refresh_token:
            self.log_test("Refresh Token", False, "No refresh token available")
            return False

        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/auth/refresh",
                json={"refresh_token": self.refresh_token},
            )
            passed = response.status_code == 200
            if passed:
                data = response.json()
                new_token = data.get("access_token")
                if new_token:
                    self.access_token = new_token
            self.log_test(
                "Refresh Token",
                passed,
                f"Status: {response.status_code}, New Token: {bool(new_token) if passed else 'N/A'}",
            )
            return passed
        except Exception as e:
            self.log_test("Refresh Token", False, f"Error: {str(e)}")
            return False

    async def test_multi_tenant_isolation(self) -> bool:
        """Test 7: Multi-tenant data isolation"""
        if not self.access_token or not self.test_tenant_id:
            self.log_test("Multi-Tenant Isolation", False, "Missing token or tenant ID")
            return False

        try:
            headers = {"Authorization": f"Bearer {self.access_token}"}

            # Create agent in user's tenant (tenant_id comes from auth token)
            agent_data = {
                "name": f"Test Agent Tenant {int(time.time())}",
                "type": "commander",
            }
            response = await self.client.post(
                f"{self.base_url}/api/v1/agents", json=agent_data, headers=headers
            )

            if response.status_code in [200, 201]:
                agent_id = response.json().get("id")
                agent_tenant_id = response.json().get("tenant_id")

                # Verify agent was created in correct tenant
                tenant_match = agent_tenant_id == self.test_tenant_id

                # Register a second user to test cross-tenant access
                user2_email = f"test_user2_{int(time.time())}@example.com"
                user2_data = {
                    "email": user2_email,
                    "password": "TestPassword456!",
                    "full_name": "Test User 2",
                }
                reg_response = await self.client.post(
                    f"{self.base_url}/api/v1/auth/register", json=user2_data
                )

                if reg_response.status_code in [200, 201]:
                    # Login as second user
                    login_response = await self.client.post(
                        f"{self.base_url}/api/v1/auth/login",
                        json={"username": user2_email, "password": "TestPassword456!"},
                    )

                    if login_response.status_code == 200:
                        user2_token = login_response.json().get("access_token")
                        user2_headers = {"Authorization": f"Bearer {user2_token}"}

                        # Try to access first user's agent (should fail)
                        response2 = await self.client.get(
                            f"{self.base_url}/api/v1/agents/{agent_id}",
                            headers=user2_headers,
                        )

                        # Should return 403 or 404 (tenant isolation enforced)
                        isolation_works = response2.status_code in [403, 404]
                        passed = tenant_match and isolation_works
                    else:
                        passed = False
                else:
                    passed = False
            else:
                passed = False

            self.log_test(
                "Multi-Tenant Isolation",
                passed,
                f"Agent creation: {response.status_code}, Isolation: {passed}",
            )
            return passed
        except Exception as e:
            self.log_test("Multi-Tenant Isolation", False, f"Error: {str(e)}")
            return False

    async def test_logout(self) -> bool:
        """Test 8: User logout"""
        if not self.access_token:
            self.log_test("User Logout", False, "No access token available")
            return False

        try:
            headers = {"Authorization": f"Bearer {self.access_token}"}
            response = await self.client.post(
                f"{self.base_url}/api/v1/auth/logout", headers=headers
            )
            passed = response.status_code in [200, 204]
            self.log_test("User Logout", passed, f"Status: {response.status_code}")
            return passed
        except Exception as e:
            self.log_test("User Logout", False, f"Error: {str(e)}")
            return False

    async def test_access_after_logout(self) -> bool:
        """Test 9: Access protected endpoint after logout (should fail)"""
        if not self.access_token:
            self.log_test("Access After Logout", False, "No access token available")
            return False

        try:
            headers = {"Authorization": f"Bearer {self.access_token}"}
            response = await self.client.get(
                f"{self.base_url}/api/v1/agents", headers=headers
            )
            # Should return 401 or 403 after logout
            passed = response.status_code in [401, 403]
            self.log_test(
                "Access After Logout (Should Fail)",
                passed,
                f"Status: {response.status_code} (Expected 401/403)",
            )
            return passed
        except Exception as e:
            self.log_test("Access After Logout", False, f"Error: {str(e)}")
            return False

    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 60)
        print("AUTHENTICATION TEST SUMMARY")
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

        return pass_rate >= 80

    def save_results(self, filename: str = "test_results_auth.json"):
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
    """Run all authentication tests"""
    print("=" * 60)
    print("OMNIPATH V5.0 - AUTHENTICATION & AUTHORIZATION TEST")
    print("Built with Pride for Obex Blackvault")
    print("=" * 60)
    print()

    async with OmnipathAuthTest() as tester:
        # Run all tests in sequence
        await tester.test_register_user()
        await tester.test_login()
        await tester.test_access_protected_endpoint()
        await tester.test_access_without_token()
        await tester.test_access_with_invalid_token()
        await tester.test_refresh_token()
        await tester.test_multi_tenant_isolation()
        await tester.test_logout()
        await tester.test_access_after_logout()

        # Print summary
        success = tester.print_summary()

        # Save results
        tester.save_results()

        return success


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)
