# System-Wide Cleanup Inventory

**Branch:** `chore/system-wide-cleanup`  
**Base:** `origin/main` after PR #400 / #401  
**Date:** 2026-08-03  

This is the code-backed inventory for the production cleanup pass. Implemented items
are proven by deployment contract tests under `tests/deployment/`. Deferred items
remain explicit so they are not treated as silent non-goals.

## Implemented in this bundle

| ID | Severity | Finding | Fix |
| :--- | :--- | :--- | :--- |
| REL-01 | P0 | Git tag `v1.1.0` pointed at an April commit while every main push rewrote container tag `1.1.0` from newer code | Release workflow now publishes version image tags **only** when the git tag is newly created; always publishes `:latest` + `sha-*` |
| REL-02 | P0 | GitHub Release recreated/updated on every main push for the same version | Release job runs only when a new version tag is created |
| REL-03 | P0 | Project stayed at `1.1.0` for hundreds of commits after the tag was frozen | Version bumped to **1.2.0** so the next main merge creates a clean immutable `v1.2.0` + matching images |
| IMG-01 | P0 | Root `Dockerfile` (CI/GHCR) lacked the autonomy disclaimer catalog required at `/app/docs/product/...` | Catalog copied into root + API images |
| IMG-02 | P0 | Root API image and `deploy/docker/api.Dockerfile` drifted (hardening, catalog, install path) | Multi-stage parity for root + api Dockerfiles |
| IMG-03 | P1 | Python images ran as root despite k8s `runAsUser: 1000` | Non-root `USER 1000` on api/worker/migrate (+ hubspot adapter) |
| IMG-04 | P1 | Runtime images installed `build-essential` | Multi-stage build; runtime only gets `libpq5` (+ curl where needed) |
| IMG-05 | P1 | No `.dockerignore` — secrets, `node_modules`, tests, `.git` could enter build context | Added repository `.dockerignore` |
| SEC-01 | P1 | Frontend Dockerfile declared empty `VITE_DEFAULT_API_KEY` / `VITE_DEFAULT_TENANT_ID` ENV keys (credential-shaped image metadata) | Removed; only non-secret `VITE_API_BASE_URL=` remains |
| SEC-02 | P1 | Disclaimer catalog path assumed source layout only | Multi-path resolution + optional `AJENDA_AUTONOMY_DISCLAIMER_CATALOG` override |
| CI-01 | P2 | `actions/setup-node@v4` (Node 20 action runtime deprecation warnings) | Bumped to `actions/setup-node@v6` |
| CI-02 | P2 | CI/release workflows lacked least-privilege default permissions | `permissions: contents: read` defaults; write elevated per job |
| REL-04 | P2 | Worker/migrate/frontend publish lacked SBOM/provenance | Added `provenance` + `sbom` to those build-push steps |

## Deferred (require product/architecture judgment)

| ID | Severity | Finding | Why deferred | Recommended follow-up |
| :--- | :--- | :--- | :--- | :--- |
| REG-01 | P1 | k8s manifests use placeholder `ajenda/api` while release publishes `ghcr.io/<org>/<repo>` | Registry naming + pull-secret wiring is environment-specific | Align manifests via Kustomize/Helm values; keep contract tests version-synced |
| REG-02 | P1 | `hubspot-crm-adapter` k8s image still uses `:latest` | Adapter publish path is separate from main release matrix | Version-pin and add to release publish + contract guard |
| SEC-03 | P2 | Frontend still supports `VITE_DEFAULT_API_KEY` for local Dev Console only | Dev ergonomics; not baked into images after SEC-01 | Longer-term: remove browser-held API keys; session/OIDC only |
| SEC-04 | P2 | Local `frontend/.env` may contain real bootstrap keys (gitignored) | Operator machine hygiene, not repo content | Document rotation in SECRETS.md if a key was ever shared |
| IMG-06 | P2 | nginx frontend final stage still root-capable (official nginx image default) | Needs careful nginx master/worker split + write paths | Hardening pass on frontend runtime user |
| IMG-07 | P2 | Ingress image copies local TLS material at build time when present | Certs are gitignored; generate-certs is the path | Fail build if unexpected cert material appears in context |
| CI-03 | P2 | Trivy scans only the API image | Cost/time tradeoff | Matrix Trivy across worker/migrate/frontend |
| CI-04 | P3 | Remaining workflows without explicit `permissions:` blocks | Lower risk with org defaults | Sweep remaining workflows |
| DOC-01 | P3 | Historical docs still say “as of v1.1.0” for policy effective dates | Intentional historical anchor | Leave unless rewriting policy history |
| OPS-01 | P1 | Historical GHCR `*:1.1.0` tags may still point at last rewritten digest | Cannot rewrite git history of prior pushes from here | Retire `1.1.0` pulls; prefer `1.2.0` / `sha-*` / digest pins |

## Proof surfaces

- `tests/deployment/test_release_identity_contract.py`
- `tests/deployment/test_docker_image_hardening_contract.py`
- `tests/deployment/test_docker_entrypoint_contract.py`
- `tests/deployment/test_frontend_deploy_contract.py`
- `tests/deployment/test_frontend_supply_chain_contract.py`
- `tests/deployment/test_k8s_image_version_contract.py`
- unit coverage for autonomy catalog load path (existing + path resolution)

## Operator notes after merge

1. First main push after merge creates `v1.2.0` and immutable image tags `*:1.2.0`.
2. Subsequent main pushes without a version bump publish only `:latest` and `sha-*`.
3. Bump `project.version` in `pyproject.toml` (and k8s version labels/images) deliberately for each release.
4. Rebuild local Compose images — running stacks from pre-cleanup images will not match this tree.
