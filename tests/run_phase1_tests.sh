#!/bin/bash
# Phase 1 Test Runner for Omnipath v5.0
# Built with Pride for Obex Blackvault

set -e

echo "========================================"
echo "OMNIPATH V5.0 - PHASE 1 TEST SUITE"
echo "Built with Pride for Obex Blackvault"
echo "========================================"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if backend is running
echo "🔍 Checking if backend is running..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Backend is running${NC}"
else
    echo -e "${RED}❌ Backend is not running${NC}"
    echo "Please start the backend first:"
    echo "  docker-compose -f docker-compose.v3.yml up -d"
    exit 1
fi

echo ""

# Install test dependencies
echo "📦 Installing test dependencies..."
pip install -q httpx pytest pytest-asyncio

echo ""

# Run End-to-End Tests
echo "========================================"
echo "TEST 1: END-TO-END INTEGRATION"
echo "========================================"
python3 tests/integration/test_end_to_end.py
E2E_RESULT=$?

echo ""
echo ""

# Run Authentication Tests
echo "========================================"
echo "TEST 2: AUTHENTICATION & AUTHORIZATION"
echo "========================================"
python3 tests/integration/test_auth.py
AUTH_RESULT=$?

echo ""
echo ""

# Run Performance Tests
echo "========================================"
echo "TEST 3: PERFORMANCE BASELINE"
echo "========================================"
python3 tests/performance/test_baseline.py
PERF_RESULT=$?

echo ""
echo ""

# Final Summary
echo "========================================"
echo "PHASE 1 TEST SUMMARY"
echo "========================================"

if [ $E2E_RESULT -eq 0 ]; then
    echo -e "${GREEN}✅ End-to-End Tests: PASSED${NC}"
else
    echo -e "${RED}❌ End-to-End Tests: FAILED${NC}"
fi

if [ $AUTH_RESULT -eq 0 ]; then
    echo -e "${GREEN}✅ Authentication Tests: PASSED${NC}"
else
    echo -e "${RED}❌ Authentication Tests: FAILED${NC}"
fi

if [ $PERF_RESULT -eq 0 ]; then
    echo -e "${GREEN}✅ Performance Tests: PASSED${NC}"
else
    echo -e "${RED}❌ Performance Tests: FAILED${NC}"
fi

echo "========================================"

# Check if all tests passed
if [ $E2E_RESULT -eq 0 ] && [ $AUTH_RESULT -eq 0 ] && [ $PERF_RESULT -eq 0 ]; then
    echo -e "${GREEN}🎉 ALL PHASE 1 TESTS PASSED!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Review test results in test_results_*.json files"
    echo "  2. Proceed to Phase 2: Monitoring & Observability"
    exit 0
else
    echo -e "${RED}❌ SOME TESTS FAILED${NC}"
    echo ""
    echo "Please review the test output above and fix the issues."
    echo "Test results are saved in test_results_*.json files."
    exit 1
fi
