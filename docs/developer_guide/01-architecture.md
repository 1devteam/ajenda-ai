# OmniPath Architecture

This document provides a high-level overview of the OmniPath v2 architecture. It is intended for developers who want to understand the core components and design patterns used in the platform.

## Core Design Patterns

OmniPath is built on a foundation of three key architectural patterns that enable its scalability, resilience, and auditability.

1.  **Event-Driven Architecture (EDA)**: The entire system is decoupled and communicates asynchronously via a **NATS.io** event bus. Instead of direct service-to-service calls, components publish events (e.g., `MissionCreated`, `AgentActionTaken`) and subscribe to the events they are interested in. This makes the system highly scalable and resilient to individual component failures.

2.  **Event Sourcing**: We do not just store the current state of an entity (like an agent or mission); we store the full sequence of events that led to that state. This provides a complete, immutable audit trail of everything that has ever happened in the system. It also allows us to reconstruct the state of any entity at any point in time, which is invaluable for debugging and analytics.

3.  **Command Query Responsibility Segregation (CQRS)**: The model for changing state (Commands) is separate from the model for reading state (Queries). 
    -   **Commands** (e.g., `CreateAgentCommand`) are processed by command handlers, which validate the command and publish events.
    -   **Queries** are handled by separate read models (projections) that are optimized for efficient data retrieval. These read models are updated asynchronously by listening to the event stream.
    This separation allows us to scale the read and write sides of the system independently.

## Key Components

| Component | Description | Location |
|---|---|---|
| **FastAPI Application** | The main entry point for the platform. It exposes the REST API and handles all incoming requests. | `backend/main.py` |
| **API Routers** | Defines all the API endpoints for the various domains (agents, missions, governance, etc.). | `backend/api/routes/` |
| **Event Store** | The persistence layer for our event-sourced entities. It uses PostgreSQL to store the immutable log of events. | `backend/core/event_sourcing/` |
| **Command & Query Buses** | The in-memory buses that route commands and queries to their respective handlers. | `backend/core/cqrs/` |
| **Saga Orchestrator** | Manages long-running, distributed transactions (sagas) to ensure data consistency across multiple steps. | `backend/core/saga/` |
| **Agent Implementations** | The concrete logic for each agent type (Commander, Researcher, etc.). | `backend/agents/implementations/` |
| **Observability Stack** | Integrated tooling for metrics, tracing, and logging. | `monitoring/` |

## Data Flow: Creating a Mission

To illustrate how these components work together, here is the typical data flow when a new mission is created:

1.  A user makes a `POST` request to `/api/v1/missions`.
2.  The `missions` API router receives the request, validates the input, and creates a `StartMissionCommand`.
3.  The command is dispatched to the **Command Bus**.
4.  The `StartMissionCommandHandler` receives the command.
5.  The handler validates the business logic (e.g., does the agent exist? does the user have permission?).
6.  If validation passes, the handler publishes a `MissionStarted` event to the **NATS Event Bus**.
7.  The `MissionProjection` (a read model) listens for `MissionStarted` events and updates its own database table with the new mission's data.
8.  The `Agent` aggregate also listens for the `MissionStarted` event and begins executing the mission.

This decoupled, event-driven flow is central to the entire OmniPath platform.
