# Runtime intelligence observability verification

This directory records the structural verification baseline for the runtime
intelligence observability upgrade. The graph was regenerated from the working
tree with:

```bash
python scripts/validation/build_dependency_graph.py \
  --output /tmp/ajenda-runtime-observability-final-2.json
```

The resulting G.R.A.F.T.+ artifact is also checked in as
[`graft-final.json`](graft-final.json). It is schema `1.4`, contains 2,099 nodes and
5,806 edges, and has SHA-256 digest:

`6b6232d64d2e7e268f09783429d9f729bf390bf9f1d7717b474c9cbd1bddd8b7`

This snapshot was generated from the current working tree because the sandbox
does not permit writing `.git/index` to create a commit. Reproduce it after
committing the same files and compare the digest again. The historical
Assessment 001 artifact is not modified.

## Decision-owner evidence boundaries

- Composition records interpretation, planner, capability, and constraint
  decisions under the proposal correlation id before confirmation.
- Runtime authority records input binding and provider selection decisions on
  the task metadata at invocation time; the worker persists those facts with
  the terminal task transaction.
- Worker validation records accepted output-contract decisions only after the
  canonical validator succeeds. Rejected output remains non-mutating and is
  not converted into a successful runtime fact.
- Worker rollup records deliverable acceptance at the acceptance decision
  boundary, including bounded reasons and task counts.
- Tool completion records source partitions and provider output classification
  without copying customer or provider payloads.

The projection filters pre-mission observations by the confirmed proposal
correlation id, preventing unrelated tenant audit events from entering a
mission's causal history.
