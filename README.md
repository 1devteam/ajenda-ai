# OmniPath v2

**A Production-Grade, Multi-Agent AI Platform**

---

OmniPath is an open, extensible, and observable platform for building, deploying, and managing fleets of autonomous AI agents. It provides the complete infrastructure necessary for production-grade agentic systems, from event-driven architecture and enterprise-grade governance to a comprehensive observability stack.

This is not a toy framework. It is a complete, working system built with the same patterns used by large-scale distributed applications, ready for deployment on a single server or a Kubernetes cluster.

| | |
|---|---|
| **Version** | `7.0.1` |
| **CI Status** | ✅ Passing |
| **Test Coverage** | 37% (679 tests) |
| **License** | Proprietary |

---

## Core Features

OmniPath is built on a foundation of production-ready architectural patterns:

-   **Event-Driven Architecture**: At its core, OmniPath uses a **NATS.io** event bus for asynchronous, decoupled communication between all components. This enables high scalability and resilience.

-   **Event Sourcing & CQRS**: Agent and mission states are not just stored; they are modeled as an immutable sequence of events. This provides a complete audit trail, enables state reconstruction, and separates read/write workloads for performance.

-   **Saga Orchestration**: Manages complex, multi-step operations across agents and services with automated compensation for failures, ensuring data consistency in a distributed environment.

-   **Comprehensive Governance**: A powerful, policy-driven governance engine provides fine-grained control over agent behavior, resource access, and compliance. Features include:
    -   **Risk-Based Pricing**: High-risk operations automatically incur higher costs.
    -   **Approval Workflows**: Multi-level approval queues for sensitive actions.
    -   **Immutable Audit Trails**: Complete, tamper-proof logs of all system activity.

-   **Full-Stack Observability**: The entire platform is instrumented for deep visibility.
    -   **Distributed Tracing** with OpenTelemetry and Jaeger.
    -   **Metrics** with Prometheus.
    -   **Dashboards** with Grafana for system health, API performance, and governance.

-   **Multi-LLM Strategy**: Flexibly route tasks to the best model for the job (e.g., GPT-4 for reasoning, Claude 3.5 for safety, Gemini for speed) via a centralized `LLMService`.

---

## Technology Stack

| Category | Technology | Purpose |
|---|---|---|
| **Web Framework** | FastAPI | High-performance asynchronous API |
| **Database** | PostgreSQL 15+ | Primary data store, event store |
| **Messaging** | NATS.io | Event bus for inter-service communication |
| **Caching** | Redis | Session data, read model snapshots |
| **Observability** | OpenTelemetry, Prometheus, Jaeger, Grafana | Tracing, metrics, and dashboards |
| **Containerization**| Docker, Kubernetes | Scalable and resilient deployment |
| **Authentication** | JWT with RBAC | Secure, role-based access control |

---

## Quick Start

This project uses Docker Compose to set up a complete local development environment.

### Prerequisites

-   Docker and Docker Compose
-   Git

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd omnipath_v2
```

### 2. Configure Environment

Copy the example environment file. **This is the only file you need to edit.**

```bash
cp .env.example .env
```

Now, edit the `.env` file to add your API keys and generate security secrets. At a minimum, you need:

```env
# Generate these two secrets
SECRET_KEY=your_32_character_random_string
JWT_SECRET_KEY=your_32_character_random_string

# Add your OpenAI API key (required for core agents)
OPENAI_API_KEY=sk-...
```

### 3. Launch the Stack

Build and run all services using the production Docker Compose file.

```bash
docker-compose -f docker-compose.production.yml up --build -d
```

This command will start the entire OmniPath stack, including the backend, database, event bus, and full observability suite.

### 4. Access Services

-   **API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
-   **Grafana Dashboards**: [http://localhost:3000](http://localhost:3000) (user: `admin`, pass: `changeme`)
-   **Jaeger Tracing**: [http://localhost:16686](http://localhost:16686)
-   **NATS Monitoring**: [http://localhost:8222](http://localhost:8222)
-   **Prometheus**: [http://localhost:9090](http://localhost:9090)

### 5. Run Database Migrations

Once the backend is running, apply the initial database schema.

```bash
docker-compose -f docker-compose.production.yml exec backend alembic upgrade head
```

Your OmniPath instance is now fully operational.

---

## Project Structure

```
/omnipath_v2
├── backend/                # Main application source code
│   ├── api/                # FastAPI routes and endpoints
│   ├── agents/             # Core agent implementations and factory
│   ├── core/               # Foundational patterns (CQRS, Event Sourcing, Saga)
│   ├── database/           # SQLAlchemy models and repositories
│   ├── economy/            # Governance-based economy logic
│   ├── integrations/       # 3rd-party services (LLM, MCP, Observability)
│   ├── middleware/         # Auth, rate limiting, security headers
│   ├── models/             # Pydantic domain models
│   ├── orchestration/      # Mission execution logic
│   └── main.py             # Application entry point
├── docs/                   # Detailed architecture and design documents
├── k8s/                    # Kubernetes deployment manifests
├── monitoring/             # Prometheus, Grafana, and Nginx configurations
├── scripts/                # Utility and operational scripts
├── tests/                  # Unit, integration, and performance tests (670+)
├── .env.example            # Template for environment variables
├── docker-compose.production.yml # Production-ready Docker Compose stack
├── Dockerfile.production   # Hardened production Docker image
└── README.md               # This file
```

---

## Contributing

Contributions are welcome. Please open an issue to discuss your proposed changes before submitting a pull request.

## License

This project is proprietary and confidential. Unauthorized use, copying, or distribution is strictly prohibited.
