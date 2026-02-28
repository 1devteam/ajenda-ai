# 1. Deployment

This runbook covers deploying Omnipath v2 to a Kubernetes cluster.

## Prerequisites

- A running Kubernetes cluster
- `kubectl` configured to access the cluster
- A configured Docker registry

## Steps

1.  **Build and Push Docker Image:**
    ```bash
    docker build -t your-registry/omnipath-backend:latest .
    docker push your-registry/omnipath-backend:latest
    ```

2.  **Create Secrets:**
    Create a `secrets.yaml` file from the `k8s/secrets.yaml.template` and apply it:
    ```bash
    kubectl apply -f k8s/secrets.yaml
    ```

3.  **Apply Manifests:**
    Apply the Kubernetes manifests in order:
    ```bash
    kubectl apply -f k8s/network-policy.yaml
    kubectl apply -f k8s/deployment.yaml
    kubectl apply -f k8s/ingress.yaml
    ```

4.  **Verify Deployment:**
    Check that all pods are running and healthy:
    ```bash
    kubectl get pods -l app=omnipath-backend
    ```