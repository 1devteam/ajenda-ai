# Event Delivery Architecture

This document defines the current event delivery architecture on the rebuild line.

Event delivery is Ajenda's durable outbox foundation for tenant-owned events. It records what should be delivered, who owns it, where it should go, how many attempts have happened, and whether delivery is pending, retrying, delivered, cancelled, or dead-lettered.

## Current foundation

The current implementation has eight layers:

1. Event delivery state vocabulary.
2. Tenant-owned event delivery domain model.
3. Event delivery migration and database contract.
4. Event delivery repository state transitions.
5. Event delivery service enqueue/cancel audit surface.
6. Event delivery dispatcher coordination.
7. Event delivery transport protocol boundary.
8. HTTP event delivery transport implementation.

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
- `get_due()` selects due `pending` and `retrying` records with `FOR UPDATE SKIP LOCKED` semantics through `with_for_update(skip_locked=True)`.
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

## Dispatcher contract

`EventDeliveryDispatcher` coordinates due delivery attempts through an injected `EventDeliveryTransport` implementation.

Implemented dispatcher types:

- `EventDeliveryTransport`
- `EventDeliveryTransportResult`
- `EventDeliveryDispatchResult`
- `EventDeliveryDispatcher`

Implemented dispatcher behavior:

- asks `EventDeliveryRepository.get_due()` for due records
- skips terminal or non-attemptable records defensively
- marks each attempt as `delivering`
- flushes the `delivering` claim before transport is called
- calls the injected transport boundary
- marks successful transport results as `delivered`
- converts transport failure results into retry or dead-letter transitions
- converts transport exceptions into failed attempts
- returns attempted, delivered, retrying, and dead-lettered counts

The dispatcher performs no direct network I/O. Network behavior belongs behind the `EventDeliveryTransport` protocol.

## HTTP transport contract

`HttpEventDeliveryTransport` is the current HTTP implementation behind the event delivery transport protocol.

Implemented HTTP transport types:

- `HttpEventDeliveryTransport`
- `HttpEventDeliveryTransportConfig`

Implemented HTTP transport behavior:

- sends event delivery payloads as JSON through `httpx`
- sends delivery, tenant, event type, and idempotency metadata as Ajenda-owned headers
- treats 2xx responses as successful transport results
- treats non-2xx responses as transport failures
- treats timeout and request errors as transport failures
- applies `HttpEventDeliveryTransportConfig.timeout_seconds` to injected clients and internally created clients
- strips reserved Ajenda header collisions case-insensitively before applying transport-owned metadata
- preserves non-reserved custom headers from `EventDelivery.headers_json`

Reserved transport-owned headers:

- `Content-Type`
- `User-Agent`
- `X-Ajenda-Delivery-Id`
- `X-Ajenda-Tenant-Id`
- `X-Ajenda-Event-Type`
- `X-Ajenda-Idempotency-Key`

The HTTP transport does not register endpoints, perform signing, own retry scheduling, or run a worker loop. It only converts a single `EventDelivery` record into one HTTP delivery attempt and returns an `EventDeliveryTransportResult`.

## Proof gates

The event delivery foundation is protected by six proof layers.

Foundation unit tests:

- `tests/unit/events/test_event_delivery_foundation.py`

Contract hardening tests:

- `tests/contract/test_event_delivery_contracts.py`

Architecture documentation contract tests:

- `tests/contract/test_event_delivery_architecture_doc.py`

Opt-in live persistence tests:

- `tests/integration/events/test_event_delivery_persistence_real.py`

Dispatcher tests:

- `tests/unit/events/test_event_delivery_dispatcher.py`
- `tests/integration/events/test_event_delivery_dispatcher_real.py`

HTTP transport tests:

- `tests/unit/events/test_event_delivery_http_transport.py`

The live persistence proofs skip unless `AJENDA_TEST_DATABASE_URL` is set. This matches the repo's existing live dependency pattern and keeps the default validation suite deterministic.

The dispatcher live persistence proof also avoids deleting unrelated live database rows. It skips when unrelated due event deliveries already exist and cleans up test-owned rows in `finally` blocks.

## Current boundary

Implemented now:

- durable event delivery table
- event delivery state vocabulary
- tenant-scoped idempotency contract
- repository state transitions
- enqueue/cancel service surface
- audit event creation for enqueue/cancel
- dispatcher coordination contract
- transport protocol boundary
- HTTP event delivery transport implementation
- HTTP transport timeout enforcement
- HTTP transport reserved header protection
- claim flush before transport
- transport exception failure handling
- `FOR UPDATE SKIP LOCKED` due-row selection
- default contract proof
- opt-in live persistence proof
- opt-in dispatcher persistence proof
- dispatcher live cleanup hardening
- mocked HTTP transport proof

Not implemented yet:

- HTTP webhook routes
- delivery endpoint registration
- signing or signature verification
- retry worker loop
- dead-letter operations API
- webhook reliability summary API

## Strategic direction

Event delivery is the messenger layer for mission-driven execution.

Mission-driven execution decides and performs work. Event delivery records and reports what happened. This lets Ajenda notify external systems without turning runtime actions into hidden network side effects.

The next implementation layer should connect the existing dispatcher and HTTP transport through an explicit runtime/worker entry point while preserving these constraints:

- tenant ownership remains mandatory
- idempotency remains tenant-scoped
- delivery attempts remain durable
- due delivery selection remains lock-safe
- claims are flushed before transport is invoked
- transport exceptions move through retry and dead-letter states
- reserved Ajenda headers cannot be spoofed by custom headers
- repository code remains transport-free
- audit evidence remains visible
