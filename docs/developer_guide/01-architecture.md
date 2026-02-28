# 1. Architecture Overview

Omnipath v2 is built on a foundation of modern, scalable, and resilient architectural patterns.

## Core Principles

- **Event Sourcing:** The state of the system is determined by a sequence of events. This provides a complete audit log, enables powerful analytics, and simplifies debugging.
- **CQRS (Command Query Responsibility Segregation):** The model for writing data (Commands) is separate from the model for reading data (Queries). This allows each side to be optimized independently.
- **Agent-Based Model:** The core logic is encapsulated in autonomous agents that communicate via a message bus.

## Key Components

- **FastAPI Backend:** A high-performance Python web framework.
- **PostgreSQL:** The primary database for storing events and projections.
- **NATS:** A lightweight, high-performance message bus for inter-agent communication.
- **Redis:** Used for caching and rate limiting.
- **Docker & Kubernetes:** The entire platform is containerized and ready for cloud-native deployment.