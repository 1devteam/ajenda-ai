"""
Quick API Endpoint Test
Tests the newly created tenant, agent, and mission endpoints
"""
import requests
import json

BASE_URL = "http://localhost:8000"


def test_endpoints():
    """Test all new endpoints"""
    print("=" * 60)
    print("Testing Omnipath API Endpoints")
    print("=" * 60)
    
    # Test health endpoint
    print("\n1. Testing Health Endpoint...")
    response = requests.get(f"{BASE_URL}/health")
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        print(f"   ✅ Health check passed")
    else:
        print(f"   ❌ Health check failed")
        return
    
    # Test tenant creation
    print("\n2. Testing Tenant Creation...")
    tenant_data = {
        "name": "Test Tenant",
        "description": "Test tenant for API validation"
    }
    response = requests.post(f"{BASE_URL}/api/v1/tenants", json=tenant_data)
    print(f"   Status: {response.status_code}")
    if response.status_code == 201:
        tenant = response.json()
        tenant_id = tenant["id"]
        print(f"   ✅ Tenant created: {tenant_id}")
    else:
        print(f"   ❌ Tenant creation failed: {response.text}")
        return
    
    # Test agent creation
    print("\n3. Testing Agent Creation...")
    agent_data = {
        "name": "Test Agent",
        "type": "custom",
        "tenant_id": tenant_id,
        "model": "gpt-4",
        "temperature": 0.7,
        "capabilities": ["web_search", "code_execution"]
    }
    response = requests.post(f"{BASE_URL}/api/v1/agents", json=agent_data)
    print(f"   Status: {response.status_code}")
    if response.status_code == 201:
        agent = response.json()
        agent_id = agent["id"]
        print(f"   ✅ Agent created: {agent_id}")
    else:
        print(f"   ❌ Agent creation failed: {response.text}")
        return
    
    # Test mission creation
    print("\n4. Testing Mission Creation...")
    mission_data = {
        "objective": "Test mission objective",
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "priority": "normal",
        "context": {"test": True}
    }
    response = requests.post(f"{BASE_URL}/api/v1/missions", json=mission_data)
    print(f"   Status: {response.status_code}")
    if response.status_code == 201:
        mission = response.json()
        mission_id = mission["id"]
        print(f"   ✅ Mission created: {mission_id}")
    else:
        print(f"   ❌ Mission creation failed: {response.text}")
        return
    
    # Test list endpoints
    print("\n5. Testing List Endpoints...")
    
    response = requests.get(f"{BASE_URL}/api/v1/tenants")
    print(f"   Tenants: {response.status_code} - {len(response.json())} found")
    
    response = requests.get(f"{BASE_URL}/api/v1/agents")
    print(f"   Agents: {response.status_code} - {len(response.json())} found")
    
    response = requests.get(f"{BASE_URL}/api/v1/missions")
    print(f"   Missions: {response.status_code} - {len(response.json())} found")
    
    # Test get endpoints
    print("\n6. Testing Get Endpoints...")
    
    response = requests.get(f"{BASE_URL}/api/v1/tenants/{tenant_id}")
    print(f"   Get Tenant: {response.status_code}")
    
    response = requests.get(f"{BASE_URL}/api/v1/agents/{agent_id}")
    print(f"   Get Agent: {response.status_code}")
    
    response = requests.get(f"{BASE_URL}/api/v1/missions/{mission_id}")
    print(f"   Get Mission: {response.status_code}")
    
    print("\n" + "=" * 60)
    print("✅ All endpoint tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        test_endpoints()
    except requests.exceptions.ConnectionError:
        print("❌ Error: Cannot connect to backend at http://localhost:8000")
        print("   Make sure the backend is running:")
        print("   docker-compose -f docker-compose.v3.yml up -d")
    except Exception as e:
        print(f"❌ Error: {e}")
