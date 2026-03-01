# Contribution Guidelines

We welcome contributions to OmniPath. To ensure a smooth and effective process, please follow these guidelines.

## The Pride Workflow

All contributions are expected to adhere to the **Pride Workflow**, which emphasizes proper actions, thoroughness, and a commitment to quality.

> "Demonstrations of pride is the equivalence of small PROPER actions you take within a process. For example, when fixing an issue with a file you go about it properly: read and understand all available data, reading a file completely to ensure understanding. Improperly on the other hand would be assuming info that is available to be known, cutting corners to save time, skimming over information, not following basic best practices. To the level you do one or the other accounts for the amount of pride you put into something."
> — Obex Blackvault

This means:

-   **Read Completely**: Understand the existing code and context before making changes.
-   **Understand Fully**: Do not guess. Ask questions if you are unsure.
-   **Plan Properly**: Think through the implications of your changes.
-   **Execute Systematically**: Write clean, well-documented code.
-   **Test Thoroughly**: Add tests for your changes and ensure all existing tests pass.

## Pull Request Process

1.  **Fork the repository** and create a new branch from `main`.
2.  **Make your changes.** Ensure your code adheres to the [Coding Standards](./04-coding-standards.md).
3.  **Add or update tests** for your changes.
4.  **Run the full test suite** locally to ensure everything passes.
5.  **Submit a pull request** to the `main` branch.
6.  **Write a clear and descriptive pull request message**, explaining the "what" and "why" of your changes.
7.  **Engage in the code review process.** Be responsive to feedback and questions.

## Commit Messages

We follow the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification. This allows for automated changelog generation and semantic versioning.

Your commit messages should be structured as follows:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Example:**

```
feat(api): add endpoint for listing agent tools

This commit introduces a new endpoint, GET /api/v1/agents/{agent_id}/tools,
which returns a list of tools available to a specific agent. This is
necessary for the upcoming UI feature that allows users to inspect
agent capabilities.

Fixes #123
```

**Common Types:**

-   `feat`: A new feature.
-   `fix`: A bug fix.
-   `docs`: Documentation only changes.
-   `style`: Changes that do not affect the meaning of the code (white-space, formatting, etc.).
-   `refactor`: A code change that neither fixes a bug nor adds a feature.
-   `perf`: A code change that improves performance.
-   `test`: Adding missing tests or correcting existing tests.
-   `chore`: Changes to the build process or auxiliary tools.
