# Runtime Evidence Substrate

## Owner and scope

The substrate extends the existing append-only `audit_events` ledger. It does
not create a second event database, replace `governance_events`, or replace
`evidence_records`.

- `audit_events` owns producer facts about lifecycle operations and decisions.
- `governance_events` remains the durable authority/decision ledger.
- `evidence_records` remains durable provider/tool/artifact proof.
- `assurance_snapshots` remains a derived, append-only read model.

`RuntimeEvidenceLedger.append_fact` writes a schema-versioned envelope under
`payload_json.runtime_evidence` in the same transaction as the producer's
existing audit fact. The envelope includes a producer, event identity, causal
and correlation identifiers, authority context, minimised subject references,
evidence references, and a canonical SHA-256 integrity digest.

## UPG/LAP

**Responsibility.** Producers emit only facts they own. Consumers read verified
envelopes and derive findings; they neither queue work nor mutate canonical
runtime state.

**Dependencies.** Mission confirmation, execution admission, worker start,
worker completion/failure, `audit_events`, `evidence_records`, continuous
assurance, tenant-scoped sessions, and the worker lease/queue spine.

**Pitfalls.** Legacy audit rows have no envelope; consumer failures must not
break producers; JSON tampering or mismatched row/envelope identity must be
visible; raw customer instructions and provider payloads must not be copied
into a general ledger; historic records must not be reclassified as violations.

**Invariants.**

1. Fact producers write through the existing tenant-scoped audit ledger.
2. Envelope integrity includes the event identity and tenant/mission binding.
3. Legacy rows remain readable and are not treated as malformed evidence.
4. Assurance consumers only append assurance observations.
5. The envelope carries minimised references, not raw customer/provider data.

**Proof.** Unit tests verify contract versioning, integrity rejection, and
independent consumer behavior. Runtime dispatcher tests verify transactional
worker facts. The VR01 Phoenix HVAC case continues to pass as an
evaluation-only composition regression; confirmation emits a minimised
composition fact when a proposal becomes a mission.

## Consumers

`consume_runtime_security_evidence` verifies envelope integrity and ledger-row
binding. `consume_intelligence_flow_evidence` derives the first missing stage
among composition, admission, and worker start. Both return read-only findings.
Continuous assurance consumes these findings alongside the existing
mission-runtime projection; it never reinterprets the mission or authorizes
execution.

## Migration and compatibility

No database migration is required for version 1: the durable `payload_json`
column already owns extensible audit facts. Historical rows remain valid legacy
audit records and are intentionally not backfilled. A future indexed consumer
query or immutable database trigger requires a separately reviewed migration;
it must retain this envelope and preserve the existing ledger owner.
