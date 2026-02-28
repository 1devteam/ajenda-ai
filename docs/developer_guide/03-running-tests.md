# 3. Running Tests

The test suite is critical for maintaining code quality and preventing regressions.

## Unit Tests

Unit tests cover individual components in isolation. They are fast and should be run frequently during development.

```bash
pytest -m unit
```

## Integration Tests

Integration tests verify the interaction between multiple components. They require the full stack to be running.

```bash
pytest -m integration
```

## Performance Tests

Performance tests measure the system's behavior under load.

```bash
pytest -m performance
```

## Running All Tests

To run the entire suite:

```bash
pytest
```