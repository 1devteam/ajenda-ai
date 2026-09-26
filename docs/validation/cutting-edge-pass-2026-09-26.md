# Cutting-Edge Runtime Pass — 2026-09-26

This is a GRAFT+ validation artifact for the existing Ajenda AI program. It records the
remaining-gap pass after the ten-mission campaign and the broadened local fixture rollout.

## Results

- Local fixture lanes now cover software development/Austin, HVAC/Dallas, roofing/Austin, and
  plumbing/Austin.
- Canonical operator missions for HVAC, roofing, and plumbing each completed with three
  prospects, five completed tasks, five persisted evidence records, no contradiction, and no
  first divergence.
- Provider-boundary integration proof passed: 14 tests covering credential authority, governed
  egress, plugin/brain separation, and fail-closed behavior.
- The stray `compose` Docker project was stopped without removing volumes. The canonical
  `ajenda-ai` API, worker, database, queue, and frontend remain healthy; `/health` and
  `/readiness` both pass.

## Evidence authority

The JSON emitted by `operator-mission-proof.py` is a disposable diagnostic export. The durable
source of truth is the tenant-scoped runtime evidence projection assembled from persisted
mission, execution-task, lease, lineage, and evidence records by the mission-deliverable API.
This distinction prevents a missing local export from being mistaken for missing runtime proof.

## Explicit non-goal

Live Gmail, HubSpot, LinkedIn, Salesforce, and Google provider effects remain credential-gated.
No credentials were invented, copied, or used for outbound sends or writes in this pass. Their
local authority and fail-closed contracts are tested; live provider effect proof requires an
operator-supplied tenant credential and remains a separate opt-in lane.
