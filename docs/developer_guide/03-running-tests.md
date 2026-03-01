# Running Tests

OmniPath has a comprehensive test suite with over 670 tests, categorized into unit, integration, and performance tests. Running these tests is a critical part of the development workflow.

## Setting Up the Test Environment

Tests should be run inside the `backend` Docker container to ensure they have access to all necessary services (like the database and event bus).

First, shell into the running `backend` container:

```bash
docker-compose -f docker-compose.production.yml exec backend bash
```

Once inside the container, you can run the test suite using `pytest`.

## Running Test Categories

The test suite is organized using `pytest` markers, allowing you to run specific categories of tests.

### Unit Tests

Unit tests are fast and test individual functions or classes in isolation. They do not require external services.

```bash
pytest -m unit
```

### Integration Tests

Integration tests verify the interaction between different components of the system (e.g., API endpoints and the database). They require the full stack to be running.

```bash
pytest -m integration
```

### Performance Tests

Performance tests measure the latency and resource usage of key operations to track performance regressions.

```bash
pytest -m performance
```

## Running All Tests

To run the entire test suite, simply run `pytest` with no arguments.

```bash
pytest
```

## Test Coverage

To generate a test coverage report, use the `--cov` flag. This will show you which parts of the codebase are covered by tests.

```bash
pytest --cov=backend
```

An HTML version of the report can be generated for more detailed analysis:

```bash
pytest --cov=backend --cov-report=html
```

The report will be generated in the `htmlcov` directory. You can copy it out of the container to view it in your browser.

```bash
# From your host machine
docker cp <container_id>:/app/htmlcov ./htmlcov
```

Maintaining a high level of test coverage and ensuring all tests pass before committing code is a core part of the OmniPath development process.
