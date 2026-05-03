# Deployment Hardening Checkpoint

## Purpose

This note records the completed deployment-hardening checkpoint after the observability, proof, Kubernetes, Docker, shell-script, and security-context guard slices landed.

It is an evidence note, not a replacement for the live runtime proof release gate or the live runtime validation matrix.

---

## Completed scope

The checkpoint covers the deployment validation and hardening layer completed through:

```text
b78d662d0a553f37d385fc3dcd021a548f0ee66b
```

That merge added an explicit Kubernetes API security context and extended the security-context guard to cover both API and worker deployment manifests.

Completed pull-request range:

| PR | Area | Result |
|---|---|---|
| `#79` | Kubernetes observability scrape drift guard | merged |
| `#80` | Kubernetes health/readiness probe drift guard | merged |
| `#81` | Docker entrypoint contract guard | merged |
| `#82` | prod-like Compose service contract guard | merged |
| `#83` | rollback script contract guard | merged |
| `#84` | deploy shell syntax guard | merged |
| `#85` | Kubernetes manifest inventory guard | merged |
| `#86` | Kubernetes image version guard | merged |
| `#87` | Kubernetes worker probe contract guard | merged |
| `#88` | Kubernetes worker security context guard | merged |
| `#89` | Kubernetes API security context hardening and guard parity | merged |

---

## Static validation evidence

After the deployment guard slices landed, the deployment test layer passed:

```text
pytest -q tests/deployment/
........................................................ [100%]
ruff check backend/ tests/
All checks passed!
ruff format --check backend/ tests/
271 files already formatted
```

This proves the deployment drift-guard layer was green as a single deployment-suite checkpoint.

---

## Live runtime evidence

After the deployment hardening checkpoint, the prod-like live runtime proof passed:

```text
bash -n deploy/scripts/live-runtime-proof.sh
./deploy/scripts/live-runtime-proof.sh
```

Observed result:

```text
[live-runtime-proof] live runtime proof passed
```

The proof also showed:

- Compose build completed for `api`, `worker`, and `migrate` images.
- `api`, `worker`, `db`, `redis`, `prometheus`, and `otel-collector` were running.
- API health and readiness checks passed.
- Postgres readiness passed.
- Redis ping passed.
- A real echo task was queued and completed.
- The worker lease reached `released`.
- Audit and lineage checks passed.
- `/v1/observability/metrics` was live.
- Prometheus readiness and scrape-target health passed.
- Redis lease cleanup passed.

This is the runtime confirmation that the prod-like stack still boots and completes real work after the deployment-hardening layer.

---

## Codex review handling

Codex review feedback was inspected during the security-context guard work.

A valid P2 review on PR `#88` identified that raw substring assertions could falsely pass if expected security values appeared only in comments. The guard was corrected before merge by replacing raw security-context substring checks with non-comment, YAML-block-scoped checks.

PR `#89` was checked for Codex comments before merge; none were present at validation time.

---

## Release-gate interpretation

At this checkpoint, the deployment hardening layer is considered green when all of the following are true:

- `tests/deployment/` passes.
- `ruff check backend/ tests/` passes.
- `ruff format --check backend/ tests/` passes.
- `deploy/scripts/live-runtime-proof.sh` passes static shell syntax validation.
- `deploy/scripts/live-runtime-proof.sh` passes end-to-end against the prod-like Compose stack.

This checkpoint does not remove the need to run targeted integration, contract, or full runtime suites before broader releases.

---

## Maintenance rules

When deployment manifests, Dockerfiles, deploy scripts, or the live runtime proof change, update this checkpoint only if the completed evidence or scope changes.

Do not mark a new deployment guard as covered here until it is merged and validated.

Do not use this checkpoint as a substitute for current live proof evidence; rerun the live proof for every release-critical deployment hardening change.
