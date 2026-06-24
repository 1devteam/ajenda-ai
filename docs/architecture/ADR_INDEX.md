# AJENDA-AI Architecture Decision Record (ADR) Index

This index tracks active architecture doctrines that govern implementation choices, contract boundaries, and release safety for AJENDA-AI.

All ADRs in this folder should be treated as policy-level architecture guidance and kept aligned with `PROJECT_SPEC.md`, `README.md`, `docs/architecture/SYSTEM_ARCHITECTURE.md`, and runtime-proof evidence surfaces.

**Visual system map:** [`SYSTEM_ARCHITECTURE.md`](./SYSTEM_ARCHITECTURE.md) (Mermaid flowcharts, code-aligned, updated 2026-06-21).

---

## ADR status legend

- **Accepted**: adopted and currently authoritative
- **Superseded**: replaced by a newer ADR
- **Deprecated**: no longer recommended, retained for history
- **Proposed**: draft, not yet authoritative

---

## Active ADRs

| ADR | Title | Status | Date | Scope |
|---|---|---|---|---|
| [ADR-0001](./ADR-0001-authority-classification-doctrine.md) | Authority Classification Doctrine | Accepted | 2026-05-23 | Contract authority classes and mutation boundaries |
| [ADR-0002](./ADR-0002-schema-evolution-strategy.md) | Schema Evolution Strategy | Accepted | 2026-05-23 | Backward-compatible schema and metadata evolution |
| [ADR-0003](./ADR-0003-readiness-semantics-doctrine.md) | Readiness Semantics Doctrine | Accepted | 2026-05-23 | Health/readiness dependency truth and response safety |
| [ADR-0004](./ADR-0004-worker-tenancy-strategy.md) | Worker Tenancy Strategy | Accepted | 2026-06-21 | Single-tenant vs multi-tenant worker queue polling |
| [ADR-0005](./ADR-0005-informed-autonomy-gate-policy.md) | Informed Autonomy Gate Policy | Accepted (policy) | 2026-06-23 | Replace misplaced gates with tiered disclaimers for tool/ability phases |

---

## Authoring rules

1. Keep ADRs short, explicit, and decision-focused.
2. Every ADR must define: context, decision, consequences, and verification impact.
3. Any ADR that changes runtime authority semantics must include:
   - migration impact,
   - test/validation impact,
   - rollback strategy.
4. If an ADR is superseded, update this index and link both old/new ADRs.

---

## Review cadence

- Review ADR alignment at least once per release cycle.
- Trigger immediate review when:
  - authority boundaries change,
  - schema contracts change,
  - readiness/recovery contracts change,
  - release-gating semantics change.
