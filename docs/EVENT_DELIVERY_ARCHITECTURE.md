# Event Delivery Architecture

This document defines the current event delivery architecture on the rebuild line.

Event delivery is Ajenda's durable outbox foundation for tenant-owned events. It records what should be delivered, who owns it, where it should go, how many attempts have happened, and whether delivery is pending, retrying, delivered, cancelled, or dead-lettered.

## Current foundation

The current implementation has five layers:

1. Event delivery state vocabulary.
2. Tenant-owned event delivery domain model.
3. Event delivery migration and database contract.
4. Event delivery repository state transitions.
5. Event delivery service enqueue/cancel audit surface.

## State machine

`EventDeliveryState` defines these values:

- `pending`
- `delivering`
- `retrying`
- `delivered`
- `dead_lettered`
- `cancelled`

Allowed operational flow:

```text
pending or retrying
↓
delivering
↓
delivered
```

Retry flow:

```text
pending or retrying
↓
delivering
↓
retrying
↓
delivering
↓
delivered or dead_lettered
```

Cancellation flow:

```text
pending, retrying, or delivering
↓
cancelled
```

Terminal states:

- `delivered`
- `dead_lettered`
- `cancelled`

Terminal records are not attemptable.

## Domain model

`EventDelivery` is the durable tenant-owned delivery record.

Implemented fields:

- `id`
- `tenant_id`
- `event_type`
- `destination_url`
- `status`
- `payload_json`
- `headers_json`
- `idempotency_key`
- `attempts`
- `max_attempts`
- `last_error`
- `next_attempt_at`
- `delivered_at`
- `dead_lettered_at`
- `mission_id`
- `created_at`
- `updated_at`

Implemented helpers:

- `is_terminal()`
- `can_attempt()`

## Database contract

The database table is `event_deliveries`.

The idempotency contract is tenant-scoped:

```text
tenant_id + idempotency_key
```

This is intentionally not globally unique. Two different tenants may use the same client-supplied idempotency key without blocking each other.

The migration also preserves query surfaces for:

- tenant lookup
- event type lookup
- status lookup
- mission linkage
- idempotency lookup

## Repository contract

`EventDeliveryRepository` owns persistence-facing state transitions.

Implemented operations:

- `create()`
- `get_for_tenant()`
- `get_due()`
- `mark_delivering()`
- `mark_delivered()`
- `mark_failed_attempt()`
- `cancel()`

Important repository rules:

- `create()` initializes Python-side defaults before flush, including `attempts=0` and `pending` status.
- `get_for_tenant()` rejects missing and cross-tenant records with the same not-found error.
- `mark_delivering()` only accepts attemptable records.
- `mark_delivered()` only accepts records currently marked `delivering`.
- `mark_failed_attempt()` moves records to `retrying` until `max_attempts` is reached, then moves them to `dead_lettered`.
- `cancel()` rejects already-terminal deliveries.

## Service contract

`EventDeliveryService` provides the application-facing enqueue and cancel surface.

Implemented operations:

- `enqueue()`
- `cancel()`

The service writes audit evidence for event delivery enqueue and cancellation actions. This keeps event delivery aligned with Ajenda's evidence-first architecture instead of hiding integration activity inside transport code.

## Proof gates

The event delivery foundation is protected by three proof layers.

Foundation unit tests:

- `tests/unit/events/test_event_delivery_foundation.py`

Contract hardening tests:

- `tests/contract/test_event_delivery_contracts.py`

Opt-in live persistence tests:

- `tests/integration/events/test_event_delivery_persistence_real.py`

The live persistence proof skips unless `AJENDA_TEST_DATABASE_URL` is set. This matches the repo's existing live dependency pattern and keeps the default validation suite deterministic.

## Current boundary

Implemented now:

- durable event delivery table
- event delivery state vocabulary
- tenant-scoped idempotency contract
- repository state transitions
- enqueue/cancel service surface
- audit event creation for enqueue/cancel
- default contract proof
- opt-in live persistence proof

Not implemented yet:

- HTTP webhook routes
- delivery endpoint registration
- external HTTP transport
- signing or signature verification
- retry worker loop
- dead-letter operations API
- webhook reliability summary API

## Strategic direction

Event delivery is the messenger layer for mission-driven execution.

Mission-driven execution decides and performs work. Event delivery records and reports what happened. This lets Ajenda notify external systems without turning runtime actions into hidden network side effects.

The next implementation layer should add a dispatcher around this foundation while preserving these constraints:

- tenant ownership remains mandatory
- idempotency remains tenant-scoped
- delivery attempts remain durable
- failures move through retry and dead-letter states
- transport behavior stays outside the repository
- audit evidence remains visible
