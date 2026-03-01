# Local Development Setup

This guide details how to set up a complete, local OmniPath development environment. The entire stack, including all backing services, runs in Docker.

## Prerequisites

-   **Docker and Docker Compose**: Ensure you have the latest versions installed.
-   **Git**: For cloning the repository.
-   **An IDE**: Such as Visual Studio Code, with Python support.

## Step 1: Clone and Configure

First, clone the repository and create your local environment file from the template.

```bash
git clone <your-repo-url>
cd omnipath_v2
cp .env.example .env
```

Next, open the `.env` file and configure it for local development. The key settings to review are:

-   `SECRET_KEY` and `JWT_SECRET_KEY`: Generate unique secrets for these.
-   `OPENAI_API_KEY`: Add your OpenAI key.
-   `DATABASE_URL`: The default is `sqlite:///./omnipath_dev.db`, which is fine for getting started. For full feature parity with production, you can change this to use the PostgreSQL service in Docker:
    ```env
    DATABASE_URL=postgresql://omnipath:${POSTGRES_PASSWORD}@localhost:5432/omnipath
    ```
    You will also need to set `POSTGRES_PASSWORD` in this case.
-   `DEBUG`: Set to `True` to enable hot-reloading for the FastAPI backend.

## Step 2: Launch the Stack

Use the `docker-compose.production.yml` file to launch all services. The `--build` flag will build the backend Docker image if it doesn't exist.

```bash
docker-compose -f docker-compose.production.yml up --build -d
```

This command starts all 8 services: `postgres`, `redis`, `nats`, `jaeger`, `prometheus`, `grafana`, `backend`, and `nginx`.

## Step 3: Run Database Migrations

With the services running, execute the Alembic database migrations inside the `backend` container to set up your database schema.

```bash
docker-compose -f docker-compose.production.yml exec backend alembic upgrade head
```

## Step 4: Accessing Services

Your local environment is now fully operational. You can access the various components at the following URLs:

-   **API Docs (Swagger UI)**: [http://localhost:8000/docs](http://localhost:8000/docs)
-   **Grafana Dashboards**: [http://localhost:3000](http://localhost:3000) (user: `admin`, pass: `changeme`)
-   **Jaeger Tracing**: [http://localhost:16686](http://localhost:16686)
-   **NATS Monitoring**: [http://localhost:8222](http://localhost:8222)
-   **Prometheus**: [http://localhost:9090](http://localhost:9090)

## Developing with Hot-Reloading

When `DEBUG=True` is set in your `.env` file, the `backend` service runs with `uvicorn`'s reloader enabled. To develop locally:

1.  Mount your local `backend` directory into the container by adding a volume to the `backend` service in your `docker-compose.override.yml` file (create this file if it doesn't exist):

    ```yaml
    services:
      backend:
        volumes:
          - ./backend:/app/backend
    ```

2.  Run `docker-compose -f docker-compose.production.yml -f docker-compose.override.yml up --build -d`.

Now, any changes you make to the Python files in your local `backend` directory will automatically trigger a reload of the `backend` service inside the container, allowing for a rapid development cycle.
