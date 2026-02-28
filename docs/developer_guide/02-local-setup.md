# 2. Local Development Setup

## Prerequisites

- Docker
- Docker Compose

## Running Locally

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/1devteam/onmiapath_v2.git
    cd onmiapath_v2
    ```

2.  **Create an environment file:**
    ```bash
    cp .env.example .env
    ```
    Fill in the required values in `.env`.

3.  **Start the services:**
    ```bash
    docker-compose up -d
    ```

This will start the backend API, PostgreSQL, Redis, NATS, and the full monitoring stack.

- API server: `http://localhost:8000`
- Grafana: `http://localhost:3000`
- NATS UI: `http://localhost:8222`