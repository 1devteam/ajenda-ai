# 5. Contribution Guidelines

## Pull Request Process

1.  **Fork the repository.**
2.  **Create a new branch** for your feature or bug fix.
3.  **Write clean, well-tested code** that adheres to the coding standards.
4.  **Ensure all tests pass** locally.
5.  **Submit a pull request** to the `main` branch.
6.  **Participate in the code review** process, addressing any feedback.

## Commit Messages

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification. This helps us automate changelogs and versioning.

Example:

```
feat(api): add endpoint for listing agent tools

This commit introduces a new endpoint `/api/v1/agents/{agent_id}/tools`
that returns a list of tools available to a specific agent.
```