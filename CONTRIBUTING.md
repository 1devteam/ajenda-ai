# Contributing to Citadel AI

Built with Pride for Obex Blackvault.

## Commit Convention

This project uses **[Conventional Commits](https://www.conventionalcommits.org/)** to drive automatic semantic versioning. Every commit to `main` is scanned and the VERSION is bumped accordingly.

### Format

```
<type>[optional scope]: <description>

[optional body]

[optional footer]
```

### Types and Version Impact

| Type | Description | Version Bump |
|---|---|---|
| `feat:` | New feature | **MINOR** (6.6.0 → 6.7.0) |
| `feat!:` | Breaking feature | **MAJOR** (6.6.0 → 7.0.0) |
| `fix:` | Bug fix | **PATCH** (6.6.0 → 6.6.1) |
| `perf:` | Performance improvement | **PATCH** |
| `refactor:` | Code refactor (no feature/fix) | **PATCH** |
| `revert:` | Revert a previous commit | **PATCH** |
| `chore:` | Maintenance, deps, config | none |
| `docs:` | Documentation only | none |
| `style:` | Formatting, whitespace | none |
| `test:` | Adding or fixing tests | none |
| `ci:` | CI/CD pipeline changes | none |
| `build:` | Build system changes | none |

### Breaking Changes

A breaking change is indicated by either:
1. An exclamation mark after the type: `feat!:` or `fix!:`
2. A `BREAKING CHANGE:` footer in the commit body

Both trigger a **MAJOR** version bump.

### Examples

```bash
# PATCH bump — bug fix
git commit -m "fix(auth): handle expired JWT tokens correctly"

# MINOR bump — new feature
git commit -m "feat(revenue): add lead scoring algorithm"

# MAJOR bump — breaking change
git commit -m "feat!: redesign agent API — removes v1 endpoints"

# No bump — maintenance
git commit -m "chore(deps): upgrade FastAPI to 0.115"
git commit -m "docs: update deployment guide"
git commit -m "ci: add docker layer caching"
```

## How Auto-Versioning Works

1. You push commits to `main`
2. The `Auto Version Bump` GitHub Actions workflow triggers
3. It scans all commits since the last git tag
4. It determines the highest-priority bump (major > minor > patch)
5. It updates `VERSION`, `CHANGELOG.md`, and `docker-compose.staging.yml`
6. It commits those changes with `[skip ci]` to avoid a loop
7. It creates and pushes a git tag `vX.Y.Z`

The VPS deployment is a separate step — version bumps do not auto-deploy.

## Pride Standards

All contributions must meet Obex Blackvault's Pride Protocol:

- Read entire files before modifying
- Understand the full problem before coding
- Write complete solutions, not patches
- Test before committing
- Document decisions
- Production-grade code only: type hints, docstrings, error handling
