# Getting Started with OmniPath

Welcome to OmniPath. This guide will walk you through the initial setup and first steps to get your OmniPath instance running and ready to accept missions.

## Prerequisites

Before you begin, ensure you have the following installed on your local machine:

-   **Docker**: [https://www.docker.com/get-started](https://www.docker.com/get-started)
-   **Docker Compose**: Included with Docker Desktop.
-   **Git**: [https://git-scm.com/downloads](https://git-scm.com/downloads)

## 1. Clone the Repository

First, clone the OmniPath repository to your local machine.

```bash
git clone <your-repo-url>
cd omnipath_v2
```

## 2. Configure Your Environment

OmniPath uses a single `.env` file to manage all configuration. Copy the provided example file to create your own local configuration.

```bash
cp .env.example .env
```

Next, you must edit the `.env` file to set your security keys and API credentials. Open `.env` in your text editor.

### Required Secrets

You must generate two unique secret keys for security. You can use `openssl` to generate cryptographically secure random strings.

```bash
# Generate a secret key
openssl rand -hex 32
```

Copy the output and paste it into your `.env` file for the following two values:

```env
SECRET_KEY=your_first_generated_32_character_string
JWT_SECRET_KEY=your_second_generated_32_character_string
```

### LLM API Keys

At a minimum, you need an OpenAI API key for the core agents to function.

```env
OPENAI_API_KEY=sk-...
```

You can also add keys for Anthropic, Google, and XAI (Grok) to enable the full multi-model LLM strategy.

## 3. Launch the OmniPath Stack

With your environment configured, you can now launch the entire OmniPath stack using Docker Compose. This command builds the necessary Docker images and starts all services in the correct order.

```bash
docker-compose -f docker-compose.production.yml up --build -d
```

This will start the following services:

-   `postgres`: The primary database.
-   `redis`: The caching layer.
-   `nats`: The event bus.
-   `jaeger`, `prometheus`, `grafana`: The observability stack.
-   `backend`: The main OmniPath application.
-   `nginx`: The reverse proxy.

## 4. Run Database Migrations

After the `backend` service is running, you need to apply the database schema. This sets up all the necessary tables for OmniPath to function.

```bash
docker-compose -f docker-compose.production.yml exec backend alembic upgrade head
```

## 5. Verify Your Installation

Your OmniPath instance is now live. You can verify that everything is working correctly by accessing the health check endpoint.

```bash
curl http://localhost:8000/health
```

You should see a response like this:

```json
{
  "status": "ok",
  "service": "Omnipath",
  "version": "5.0.0",
  "environment": "development",
  "observability": {
    "opentelemetry": true,
    "prometheus": true
  }
}
```

Your OmniPath instance is now ready. The next step is to create your first user account and agent.
