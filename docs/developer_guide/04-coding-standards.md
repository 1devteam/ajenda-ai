# Coding Standards

OmniPath adheres to a strict set of coding standards to maintain code quality, readability, and security. These standards are enforced automatically by the CI pipeline on every commit.

## Code Formatting

All Python code in the repository is formatted using **Black**, the uncompromising code formatter. This ensures a consistent and readable style across the entire codebase.

-   **Line Length**: 100 characters.

Before committing any code, you should format your changes:

```bash
black backend/ tests/
```

## Linting

We use **Flake8** to lint our code. Flake8 checks for a wide range of style issues and common programming errors.

Our Flake8 configuration is defined in the `.flake8` file at the root of the repository. You can run the linter locally with:

```bash
flake8 backend/ tests/
```

## Type Checking

The entire codebase is fully type-hinted. We use **MyPy** in strict mode to perform static type checking. This helps to catch a large class of bugs before the code is ever run.

To run the type checker locally:

```bash
mypy backend/
```

## Security Scanning

We use two primary tools for automated security scanning:

1.  **Bandit**: A static analysis tool that scans for common security vulnerabilities in Python code.
2.  **Safety**: A tool that checks your installed Python dependencies for known security vulnerabilities.

These checks are run as part of the CI pipeline. You can also run them locally:

```bash
# Run Bandit
bandit -r backend/

# Run Safety (make sure to install dependencies first)
pip install -r requirements.txt
safety check
```

## CI Enforcement

All of these checks—formatting, linting, type checking, and security scanning—are run as jobs in our GitHub Actions CI pipeline. A pull request cannot be merged unless all of these checks pass.

Adhering to these standards is a requirement for all contributions to the OmniPath project.
