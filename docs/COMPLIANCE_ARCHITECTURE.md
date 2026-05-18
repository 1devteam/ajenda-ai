# Ajenda AI Compliance Architecture

## Purpose

Ajenda AI treats compliance as a first-class runtime contract, not an after-the-fact policy note.

The compliance layer gives missions and execution tasks durable classification fields so governed workflows can be evaluated before execution, routed for human review when required, and audited consistently.

## Runtime contract

Compliance is represented on both major workflow records:

- `Mission`
- `ExecutionTask`

Current fields:

- `compliance_category`
- `jurisdiction`
- `requires_human_review` on execution tasks

Default classification is:

```text
category: operational
jurisdiction: global
requires_human_review: false
