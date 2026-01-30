#!/bin/bash
# Omnipath v4.5 Test Runner
# Runs the complete test suite with various options

set -e

echo "=========================================="
echo "Omnipath v4.5 Test Suite"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Default options
RUN_UNIT=true
RUN_INTEGRATION=true
RUN_COVERAGE=true
VERBOSE=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --unit-only)
            RUN_INTEGRATION=false
            shift
            ;;
        --integration-only)
            RUN_UNIT=false
            shift
            ;;
        --no-coverage)
            RUN_COVERAGE=false
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --help)
            echo "Usage: ./run_tests.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --unit-only          Run only unit tests"
            echo "  --integration-only   Run only integration tests"
            echo "  --no-coverage        Skip coverage report"
            echo "  --verbose            Show detailed output"
            echo "  --help               Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./run_tests.sh                    # Run all tests with coverage"
            echo "  ./run_tests.sh --unit-only        # Run only unit tests"
            echo "  ./run_tests.sh --verbose          # Run with detailed output"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}Error: pytest is not installed${NC}"
    echo "Install it with: pip install pytest pytest-asyncio pytest-cov"
    exit 1
fi

# Build pytest command
PYTEST_CMD="pytest"

if [ "$VERBOSE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -vv"
else
    PYTEST_CMD="$PYTEST_CMD -v"
fi

if [ "$RUN_COVERAGE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --cov=backend --cov-report=html --cov-report=term-missing"
fi

# Run tests based on options
if [ "$RUN_UNIT" = true ] && [ "$RUN_INTEGRATION" = true ]; then
    echo -e "${GREEN}Running all tests...${NC}"
    echo ""
    $PYTEST_CMD tests/
    
elif [ "$RUN_UNIT" = true ]; then
    echo -e "${GREEN}Running unit tests only...${NC}"
    echo ""
    $PYTEST_CMD tests/unit/ -m unit
    
elif [ "$RUN_INTEGRATION" = true ]; then
    echo -e "${GREEN}Running integration tests only...${NC}"
    echo ""
    $PYTEST_CMD tests/integration/ -m integration
fi

# Check test results
if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}=========================================="
    echo "✅ All tests passed!"
    echo -e "==========================================${NC}"
    
    if [ "$RUN_COVERAGE" = true ]; then
        echo ""
        echo -e "${YELLOW}Coverage report generated in: htmlcov/index.html${NC}"
        echo "Open it in your browser to view detailed coverage"
    fi
    
    exit 0
else
    echo ""
    echo -e "${RED}=========================================="
    echo "❌ Some tests failed"
    echo -e "==========================================${NC}"
    exit 1
fi
