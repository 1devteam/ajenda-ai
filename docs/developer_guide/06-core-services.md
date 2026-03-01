# Core Services

This document provides a brief overview of the core, foundational services that power the OmniPath platform. Understanding these services is essential for any developer working on the system.

## Event Store

-   **Location**: `backend/core/event_sourcing/`
-   **Purpose**: The Event Store is the single source of truth for all state changes in the system. It persists a chronological, immutable log of all events (e.g., `AgentCreated`, `MissionStarted`, `ToolUsed`).
-   **How it Works**: Instead of updating rows in a database, we append new events to the store. The current state of any entity is derived by replaying its event history. This provides a complete audit trail and enables powerful features like point-in-time state reconstruction.

## Command and Query Buses

-   **Location**: `backend/core/cqrs/`
-   **Purpose**: These buses are the entry points for all state changes (Commands) and data retrieval (Queries).
-   **How it Works**: 
    -   The **Command Bus** receives commands, validates them, and routes them to the appropriate command handler. The handler executes the business logic and publishes one or more events.
    -   The **Query Bus** receives queries and routes them to query handlers, which read from optimized read models (projections) to return data efficiently.

## NATS Event Bus

-   **Location**: `backend/core/event_bus/`
-   **Purpose**: The NATS Event Bus is the high-performance messaging layer that enables asynchronous communication between all components of the system.
-   **How it Works**: When a service publishes an event (e.g., the `EventStore` publishes a `NewEventAppended` event), NATS delivers that event to all subscribed services in real-time. This decouples the services and allows them to react to changes without being directly called.

## Saga Orchestrator

-   **Location**: `backend/core/saga/`
-   **Purpose**: The Saga Orchestrator manages complex, long-running processes that span multiple steps or services, ensuring that they either complete successfully or are properly compensated if a failure occurs.
-   **How it Works**: A saga is defined as a sequence of steps, where each step has an `action` and a `compensation` function. The orchestrator executes the actions in order. If any action fails, it executes the compensation functions for all previously completed steps in reverse order, effectively rolling back the transaction.

These core services provide the architectural foundation that makes OmniPath a robust, scalable, and maintainable platform.
