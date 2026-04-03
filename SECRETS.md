# Secrets Management — Ajenda AI

## The Rule

**No secrets, credentials, tokens, passwords, or API keys are ever committed to this repository.**

This applies to all branches, all commits, all time. There are no exceptions.

---

## What Belongs in Git

| File | Purpose | Committed? |
| :--- | :--- | :---: |
| `.env.example` | Development template with placeholder values | ✅ Yes |
| `deploy/compose/.env.prod.example` | Production template with placeholder values | ✅ Yes |
| `deploy/k8s/secret.example.yaml` | K8s Secret manifest template | ✅ Yes |
| `.env` | Your local development secrets | ❌ Never |
| `deploy/compose/.env.prod` | Production secrets | ❌ Never |
| Any file with real credentials | — | ❌ Never |

---

## Developer Setup

```bash
# Development
cp .env.example .env
# Edit .env with your local values

# Production (Docker Compose)
cp deploy/compose/.env.prod.example deploy/compose/.env.prod
# Edit .env.prod with real production values — never commit this file
```

---

## Pre-commit Protection

This repo uses `detect-secrets` and `ruff` via pre-commit to block accidental secret commits.

```bash
# Install once per machine
pip install pre-commit
pre-commit install

# Run manually
pre-commit run --all-files
```

If a commit is blocked by `detect-secrets`, either:
1. Remove the secret from the file (correct action)
2. If it is a false positive, add it to `.secrets.baseline` with `detect-secrets audit .secrets.baseline`

---

## Production Secrets Management

For production deployments, use one of the following — **never** a `.env` file on a server:

| Platform | Solution |
| :--- | :--- |
| Kubernetes | K8s Secrets (base64-encoded) + external-secrets-operator for Vault/AWS |
| AWS | AWS Secrets Manager + IAM role for the pod/task |
| GCP | Secret Manager + Workload Identity |
| HashiCorp Vault | Vault Agent Injector or Vault Secrets Operator |
| Docker Compose (dev only) | `.env.prod` file, never committed, rotated regularly |

---

## If You Accidentally Commit a Secret

1. **Rotate the secret immediately** — assume it is compromised
2. Remove it from the file and commit the fix
3. Use `git filter-repo` or BFG Repo Cleaner to purge it from history
4. Force-push and notify the team
5. Check all logs and audit trails for unauthorized use

---

## CI Secret Scanning

The `security.yml` GitHub Actions workflow runs `gitleaks` on every PR and on a weekly schedule to scan the full commit history for secrets. Any detection fails the build.
