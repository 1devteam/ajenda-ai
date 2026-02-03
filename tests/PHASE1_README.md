# Phase 1: System Validation & Baseline Testing

**Status**: Ready to Execute  
**Priority**: 🔴 Critical  
**Estimated Time**: 2-3 days  
**Built with Pride for Obex Blackvault**

---

## Overview

Phase 1 establishes a working baseline for Omnipath v5.0 by testing all core functionality end-to-end. This phase ensures the system is stable before building additional features.

## Test Suites

### 1. End-to-End Integration Test
**File**: `tests/integration/test_end_to_end.py`  
**Tests**: 12 tests covering complete system flow

**What it tests**:
- ✅ Backend health check
- ✅ Prometheus metrics endpoint
- ✅ API documentation
- ✅ Tenant creation
- ✅ Agent creation
- ✅ Agent retrieval
- ✅ Agent listing
- ✅ Mission creation
- ✅ Mission retrieval
- ✅ Economy balance check
- ✅ Meta-learning leaderboard
- ✅ System insights

**Expected outcome**: 80%+ pass rate (10/12 tests minimum)

---

### 2. Authentication & Authorization Test
**File**: `tests/integration/test_auth.py`  
**Tests**: 9 tests covering JWT authentication and RBAC

**What it tests**:
- ✅ User registration
- ✅ User login
- ✅ Access with valid token
- ✅ Access without token (should fail)
- ✅ Access with invalid token (should fail)
- ✅ Token refresh
- ✅ Multi-tenant isolation
- ✅ User logout
- ✅ Access after logout (should fail)

**Expected outcome**: 80%+ pass rate (7/9 tests minimum)

---

### 3. Performance Baseline Test
**File**: `tests/performance/test_baseline.py`  
**Tests**: Performance metrics for key endpoints

**What it tests**:
- ✅ Health endpoint latency (target: P95 < 50ms)
- ✅ Metrics endpoint latency (target: P95 < 100ms)
- ✅ List agents latency (target: P95 < 200ms)
- ✅ Concurrent requests (10, 50, 100 users)
- ✅ System throughput (target: 50 req/sec)

**Expected outcome**: All targets met

---

## Prerequisites

### 1. Backend Running
```bash
cd ~/projects/omnipath_v2
docker-compose -f docker-compose.v3.yml up -d
```

### 2. Verify Services
```bash
# Check all containers are running
docker-compose -f docker-compose.v3.yml ps

# Test backend
curl http://localhost:8000/health

# Check metrics
curl http://localhost:8000/metrics
```

### 3. Install Test Dependencies
```bash
pip install httpx pytest pytest-asyncio
```

---

## Running Tests

### Option 1: Run All Tests (Recommended)
```bash
cd ~/projects/omnipath_v2
./tests/run_phase1_tests.sh
```

This will:
1. Check if backend is running
2. Install dependencies
3. Run all 3 test suites
4. Generate summary report
5. Save results to JSON files

### Option 2: Run Individual Tests
```bash
# End-to-End Test
python3 tests/integration/test_end_to_end.py

# Authentication Test
python3 tests/integration/test_auth.py

# Performance Test
python3 tests/performance/test_baseline.py
```

---

## Test Results

Results are saved to JSON files:
- `test_results_e2e.json` - End-to-end test results
- `test_results_auth.json` - Authentication test results
- `test_results_performance.json` - Performance test results

### Example Result Format
```json
{
  "timestamp": "2026-02-03T10:30:00",
  "total_tests": 12,
  "passed": 11,
  "failed": 1,
  "tests": [
    {
      "name": "Health Check",
      "passed": true,
      "details": "Status: 200, Service: Omnipath",
      "timestamp": "2026-02-03T10:30:01"
    }
  ]
}
```

---

## Success Criteria

Phase 1 is considered **PASSED** if:

✅ **End-to-End Tests**: 80%+ pass rate (10/12 minimum)  
✅ **Authentication Tests**: 80%+ pass rate (7/9 minimum)  
✅ **Performance Tests**: All targets met  
✅ **No critical bugs** blocking basic functionality  
✅ **Test results documented** in JSON files

---

## Troubleshooting

### Backend Not Running
```bash
# Check container status
docker-compose -f docker-compose.v3.yml ps

# View backend logs
docker logs omnipath-backend

# Restart services
docker-compose -f docker-compose.v3.yml restart
```

### Tests Failing
```bash
# Check backend health
curl http://localhost:8000/health

# Check database connection
docker exec -it omnipath-postgres psql -U omnipath -d omnipath -c "SELECT 1;"

# Check Redis
docker exec -it omnipath-redis redis-cli PING

# View detailed logs
docker logs -f omnipath-backend
```

### Connection Refused
- Ensure backend is running: `docker ps | grep omnipath-backend`
- Check port 8000 is not in use: `lsof -i :8000`
- Verify Docker network: `docker network ls`

### Authentication Tests Failing
- Check if auth endpoints exist: `curl http://localhost:8000/docs`
- Verify JWT secret is set in environment variables
- Check database has users table: `docker exec -it omnipath-postgres psql -U omnipath -d omnipath -c "\dt"`

### Performance Tests Failing
- Warm up the system first (run a few manual requests)
- Check system resources: `docker stats`
- Reduce concurrent users if system is under-resourced
- Check for other processes consuming resources

---

## Next Steps

After Phase 1 passes:

1. **Review Results**: Analyze test results and identify any issues
2. **Document Findings**: Update PROJECT_SPEC.md with any discoveries
3. **Fix Critical Bugs**: Address any blocking issues found
4. **Proceed to Phase 2**: Monitoring & Observability setup

---

## Pride-Based Testing Standards

✅ **Read all test output completely** - Don't skip failures  
✅ **Understand why tests fail** - Don't just re-run  
✅ **Fix root causes** - Not symptoms  
✅ **Test fixes thoroughly** - Before committing  
✅ **Document learnings** - For future reference  

**Pride Score Target**: 95%+ proper actions

---

## Support

For issues or questions:
1. Check test output and JSON results
2. Review backend logs: `docker logs omnipath-backend`
3. Check PROJECT_SPEC.md for architecture details
4. Review SYSCTL.md for system commands

---

**Last Updated**: 2026-02-03  
**Version**: 1.0  
**Status**: Ready for Execution
