# Validation Artifacts

This directory stores evidence captured by `scripts/validation/live_runtime_matrix.sh`.

## Layout

- `artifacts/validation/<timestamp>/RG-XX/...`
- Each scenario folder captures:
  - `status.txt`, `headers.txt`, `body.txt` from API calls
  - DB snapshots (`*.tsv`) from `psql`
  - Redis snapshots (`*.txt`) from `redis-cli`
  - audit/governance extracts
  - worker log excerpts when configured

## Usage

```bash
# all scenarios
scripts/validation/live_runtime_matrix.sh

# only safe read-only checks
scripts/validation/live_runtime_matrix.sh --group read-only

# run only one scenario
scripts/validation/live_runtime_matrix.sh --scenario RG-03
```

## Required environment variables

- `AJENDA_API_URL` (default `http://localhost:8000`)
- `AJENDA_DB_URL` (for DB evidence)
- `AJENDA_REDIS_URL` (for Redis evidence)
- `AJENDA_TENANT_ID` + `AJENDA_AUTH_HEADER` (tenant-scoped scenarios)

Optional scenario-specific IDs:

- `AJENDA_SAMPLE_TASK_ID`
- `AJENDA_FORCE_FAIL_TASK_ID`
- `AJENDA_DEAD_LETTER_TASK_ID`
- `AJENDA_PENDING_REVIEW_TASK_ID`

## Safety

- `--group read-only` is safe for shared environments.
- `--group tenant-mutations` mutates one tenant's state.
- `--group global-mutations` calls `/v1/operations/recovery` and must run only in isolated environments.
