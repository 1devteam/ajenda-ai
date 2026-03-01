# Runbook: Troubleshooting Common Issues

This runbook provides first steps for diagnosing and resolving common problems with an OmniPath deployment.

## Issue: Backend Service is Unhealthy or Crash-Looping

**Symptoms**:
-   The `/health` endpoint returns a non-200 status code.
-   `docker-compose ps` shows the `backend` container restarting.
-   In Kubernetes, `kubectl get pods` shows the backend pod in a `CrashLoopBackOff` state.

**Diagnosis Steps**:

1.  **Check the Logs**: This is always the first step. The application logs will almost always contain the root cause of the failure.

    ```bash
    # For Docker Compose
    docker-compose -f docker-compose.production.yml logs --tail=100 backend

    # For Kubernetes
    kubectl logs <backend-pod-name> -n <namespace>
    ```

2.  **Common Causes**:
    -   **Database Connection Failure**: Look for logs indicating the application cannot connect to the PostgreSQL database. Verify the `DATABASE_URL` is correct and that the `postgres` container is running and healthy.
    -   **Incorrect Environment Variables**: A misconfigured or missing environment variable can cause the application to fail on startup. Double-check your `.env` file or Kubernetes secrets.
    -   **Out of Memory (OOM)**: If the container is being killed without a clear error in the application logs, it may be an OOM issue. Check the Docker daemon logs or `kubectl describe pod <pod-name>` for OOM kill events. If this is the case, increase the memory available to the container.

## Issue: API Requests are Failing with 5xx Errors

**Symptoms**:
-   API calls are returning `500 Internal Server Error`, `502 Bad Gateway`, or `504 Gateway Timeout`.

**Diagnosis Steps**:

1.  **Check the Backend Logs**: Look for unhandled exceptions that correspond to the failing requests. The log entry should contain a full stack trace.

2.  **Check Jaeger for Traces**: If distributed tracing is enabled, find the failing request in the Jaeger UI. The trace will show you the full lifecycle of the request, including which service the error originated from and the latency of each step. This is especially useful for debugging issues in downstream services (like NATS or an external LLM API).

3.  **Check Nginx Logs (for 502/504 errors)**: If you are seeing `502 Bad Gateway` or `504 Gateway Timeout` errors, the issue may be with the Nginx reverse proxy. Check the Nginx logs for errors.

    ```bash
    docker-compose -f docker-compose.production.yml logs nginx
    ```
    A `502` error often means Nginx cannot connect to the upstream `backend` service. A `504` error means the `backend` service is not responding in time.

## Issue: Missions are Stuck in `pending` State

**Symptoms**:
-   Newly created missions are not transitioning to the `running` state.

**Diagnosis Steps**:

1.  **Check the NATS Server**: Missions are picked up by agents via the NATS event bus. Ensure the `nats` container is running and healthy. You can check its status via the monitoring UI at `http://localhost:8222`.

2.  **Check the Agent Logs**: The agent logs (which are part of the main `backend` logs) may indicate why they are not picking up new missions. Look for errors related to NATS subscriptions or message processing.

3.  **Check for Resource Starvation**: If the system is under very heavy load, it is possible that the agent workers are all busy with existing missions. Check the Grafana dashboards for CPU and memory usage to see if the system is overloaded.
