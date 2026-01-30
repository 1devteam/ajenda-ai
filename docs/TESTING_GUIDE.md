# Omnipath v4.5 Testing Guide

## Overview

This guide explains how to run and write tests for Omnipath. The test suite includes unit tests, integration tests, and end-to-end tests covering all major features.

---

## Test Structure

```
tests/
├── __init__.py
├── conftest.py              # Shared fixtures and configuration
├── unit/                    # Fast, isolated unit tests
│   ├── test_economy.py      # Economy system tests
│   └── test_auth.py         # Authentication tests
├── integration/             # Integration tests with real services
│   └── test_api_endpoints.py  # API endpoint tests
└── fixtures/                # Test data and helpers
```

---

## Running Tests

### Quick Start

Run all tests with coverage:
```bash
./run_tests.sh
```

### Test Runner Options

```bash
# Run only unit tests (fast)
./run_tests.sh --unit-only

# Run only integration tests
./run_tests.sh --integration-only

# Run without coverage report
./run_tests.sh --no-coverage

# Run with verbose output
./run_tests.sh --verbose

# Show help
./run_tests.sh --help
```

### Using Pytest Directly

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/unit/test_economy.py

# Run specific test class
pytest tests/unit/test_economy.py::TestResourceMarketplace

# Run specific test
pytest tests/unit/test_economy.py::TestResourceMarketplace::test_charge_reduces_balance

# Run tests by marker
pytest -m unit          # Only unit tests
pytest -m integration   # Only integration tests
pytest -m economy       # Only economy tests
pytest -m auth          # Only auth tests

# Run with coverage
pytest --cov=backend --cov-report=html

# Run in parallel (faster)
pytest -n auto
```

---

## Test Categories

### Unit Tests (`-m unit`)

**Fast, isolated tests** that don't require external services.

- Test individual functions and classes
- Use mocks and fixtures
- Run in milliseconds
- Located in `tests/unit/`

**Example:**
```python
@pytest.mark.unit
async def test_charge_reduces_balance(marketplace, mock_user):
    """Test that charging an agent reduces their balance"""
    # Test logic here
```

### Integration Tests (`-m integration`)

**Tests that verify components work together** correctly.

- Test API endpoints
- Test workflows
- May require running services
- Located in `tests/integration/`

**Example:**
```python
@pytest.mark.integration
def test_get_agent_balances(client, auth_headers):
    """Test retrieving agent balances via API"""
    response = client.get("/api/v1/economy/balance", headers=auth_headers)
    assert response.status_code == 200
```

### End-to-End Tests (`-m e2e`)

**Complete workflow tests** simulating real user scenarios.

- Test entire user journeys
- Verify system behavior
- Slowest but most comprehensive

**Example:**
```python
@pytest.mark.e2e
def test_agent_lifecycle_workflow(client, auth_headers):
    """Test complete agent lifecycle from creation to mission completion"""
    # Multi-step workflow test
```

---

## Writing Tests

### Test Naming Convention

- Test files: `test_*.py`
- Test classes: `Test*`
- Test functions: `test_*`

**Good names are descriptive:**
```python
# Good ✅
def test_charge_reduces_agent_balance()
def test_invalid_token_returns_401()

# Bad ❌
def test_1()
def test_charge()
```

### Using Fixtures

Fixtures provide reusable test data and setup.

**Available fixtures:**

| Fixture | Description |
|---------|-------------|
| `client` | Synchronous FastAPI test client |
| `async_client` | Asynchronous test client |
| `mock_user` | Standard user with DEVELOPER role |
| `mock_admin_user` | Admin user |
| `auth_token` | Valid JWT token |
| `auth_headers` | Authorization headers |
| `marketplace` | Fresh ResourceMarketplace instance |
| `marketplace_with_data` | Marketplace with test data |

**Example usage:**
```python
def test_protected_endpoint(client, auth_headers):
    """Test endpoint requires authentication"""
    response = client.get("/api/v1/economy/balance", headers=auth_headers)
    assert response.status_code == 200
```

### Async Tests

Use `@pytest.mark.asyncio` for async tests:

```python
@pytest.mark.asyncio
async def test_async_operation(marketplace, mock_user):
    """Test asynchronous operation"""
    result = await marketplace.get_balance(mock_user.tenant_id, "agent_1")
    assert result is not None
```

### Parametrized Tests

Test multiple scenarios with one test function:

```python
@pytest.mark.parametrize("amount,expected", [
    (10.0, 990.0),
    (50.0, 950.0),
    (100.0, 900.0),
])
async def test_charge_amounts(marketplace, mock_user, amount, expected):
    """Test charging different amounts"""
    await marketplace.charge(mock_user.tenant_id, "agent", amount, "llm_call")
    balance = await marketplace.get_balance(mock_user.tenant_id, "agent")
    assert balance["balance"] == expected
```

---

## Test Coverage

### Viewing Coverage Reports

After running tests with coverage:

```bash
# Open HTML report in browser
open htmlcov/index.html

# View terminal report
pytest --cov=backend --cov-report=term-missing
```

### Coverage Goals

- **Overall:** >80% coverage
- **Critical paths:** >95% coverage
- **New features:** 100% coverage

### Checking Coverage

```bash
# Check if coverage meets minimum threshold
pytest --cov=backend --cov-fail-under=80
```

---

## Best Practices

### 1. Test One Thing at a Time

```python
# Good ✅
def test_charge_reduces_balance():
    # Test only balance reduction

def test_charge_records_transaction():
    # Test only transaction recording

# Bad ❌
def test_charge():
    # Tests balance AND transaction AND timestamp AND...
```

### 2. Use Descriptive Assertions

```python
# Good ✅
assert response.status_code == 200, f"Expected 200, got {response.status_code}"
assert "balance" in data, "Response missing 'balance' field"

# Bad ❌
assert response.status_code == 200
assert "balance" in data
```

### 3. Clean Up After Tests

```python
@pytest.fixture
def temp_file():
    """Create temporary file for testing"""
    file_path = "/tmp/test_file.txt"
    yield file_path
    # Cleanup
    if os.path.exists(file_path):
        os.remove(file_path)
```

### 4. Mock External Services

```python
@pytest.mark.asyncio
async def test_llm_call(monkeypatch):
    """Test LLM call without actually calling OpenAI"""
    async def mock_llm_call(*args, **kwargs):
        return {"response": "mocked"}
    
    monkeypatch.setattr("backend.integrations.llm.call", mock_llm_call)
    # Test logic here
```

### 5. Test Error Cases

```python
def test_invalid_amount_rejected(client, auth_headers):
    """Test that negative amounts are rejected"""
    response = client.post(
        "/api/v1/economy/top-up?amount=-50",
        headers=auth_headers
    )
    assert response.status_code == 422  # Validation error
```

---

## Continuous Integration

### Running Tests in CI/CD

```yaml
# Example GitHub Actions workflow
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.11
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio pytest-cov
      - name: Run tests
        run: ./run_tests.sh
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

---

## Troubleshooting

### Tests Failing Locally

1. **Check dependencies:**
   ```bash
   pip install pytest pytest-asyncio pytest-cov httpx
   ```

2. **Clear pytest cache:**
   ```bash
   pytest --cache-clear
   ```

3. **Run with verbose output:**
   ```bash
   pytest -vv --tb=long
   ```

### Import Errors

Make sure you're running from the project root:
```bash
cd /home/inmoa/projects/omnipath_v2
pytest
```

### Async Test Errors

Ensure `pytest-asyncio` is installed:
```bash
pip install pytest-asyncio
```

---

## Test Markers Reference

| Marker | Description |
|--------|-------------|
| `@pytest.mark.unit` | Fast unit test |
| `@pytest.mark.integration` | Integration test |
| `@pytest.mark.e2e` | End-to-end test |
| `@pytest.mark.economy` | Economy system test |
| `@pytest.mark.auth` | Authentication test |
| `@pytest.mark.api` | API endpoint test |
| `@pytest.mark.slow` | Slow-running test |
| `@pytest.mark.asyncio` | Async test |

---

## Example Test Workflow

Here's a complete example of adding a new feature with tests:

### 1. Write the test first (TDD)

```python
# tests/unit/test_new_feature.py
@pytest.mark.unit
async def test_new_feature_works(marketplace, mock_user):
    """Test that new feature works correctly"""
    result = await marketplace.new_feature(mock_user.tenant_id)
    assert result == expected_value
```

### 2. Run the test (it should fail)

```bash
pytest tests/unit/test_new_feature.py
```

### 3. Implement the feature

```python
# backend/economy/resource_marketplace.py
async def new_feature(self, tenant_id: str):
    # Implementation here
    return result
```

### 4. Run the test again (it should pass)

```bash
pytest tests/unit/test_new_feature.py
```

### 5. Add integration test

```python
# tests/integration/test_api_endpoints.py
@pytest.mark.integration
def test_new_feature_api(client, auth_headers):
    """Test new feature via API"""
    response = client.get("/api/v1/new-feature", headers=auth_headers)
    assert response.status_code == 200
```

### 6. Run all tests

```bash
./run_tests.sh
```

---

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [Pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [Coverage.py](https://coverage.readthedocs.io/)

---

**Remember:** Good tests are your safety net. They give you confidence to refactor, add features, and deploy to production. Invest time in writing quality tests!
