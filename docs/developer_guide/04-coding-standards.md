# 4. Coding Standards

We enforce a strict set of coding standards to ensure the codebase is clean, readable, and maintainable.

- **Formatting:** All code is formatted with `black`.
- **Linting:** We use `flake8` to catch common style and logic errors.
- **Type Checking:** All code is type-hinted and checked with `mypy`.
- **Security:** `bandit` and `safety` are used to scan for security vulnerabilities.

These checks are all run automatically in the CI pipeline. To run them locally:

```bash
# Format code
black backend tests

# Run linters and type checker
flake8 backend tests
mypy backend

# Run security scans
bandit -r backend
safety check
```