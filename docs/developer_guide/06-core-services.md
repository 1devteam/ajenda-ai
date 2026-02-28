# 6. Core Services

## Event Store

The Event Store is the single source of truth. It appends all system events to an immutable log. Projections read from this log to build and maintain read models.

## NATS Bus

The NATS bus provides a publish-subscribe mechanism for real-time communication between agents and other services. It also supports request-reply patterns for synchronous interactions.

## Saga Orchestrator

The Saga Orchestrator manages long-running, distributed transactions. It ensures that a sequence of operations either completes fully or is properly compensated in case of failure. This is critical for complex workflows like mission execution.