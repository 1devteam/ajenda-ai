# Runbook: Deploying OmniPath

This runbook provides the standard operating procedure for deploying the OmniPath v2 platform. It covers both a simple Docker Compose deployment for staging and a full Kubernetes deployment for production.

## Option 1: Docker Compose Deployment (Staging / Simple Production)

This method is ideal for a single-server deployment.

### Prerequisites

-   A Linux server (Ubuntu 22.04 recommended) with Docker and Docker Compose installed.
-   A domain name pointed at the server's IP address.
-   The OmniPath repository cloned onto the server.

### Deployment Steps

1.  **Configure Environment**: Copy `.env.example` to `.env` and fill in all required values, especially the production database password, Redis password, and security secrets.

    ```bash
    cp .env.example .env
    nano .env
    ```

2.  **Launch Stack**: Use the `docker-compose.production.yml` file to start all services.

    ```bash
    docker-compose -f docker-compose.production.yml up --build -d
    ```

3.  **Run Migrations**: Apply the database schema.

    ```bash
    docker-compose -f docker-compose.production.yml exec backend alembic upgrade head
    ```

4.  **Configure Nginx**: The `nginx` service acts as a reverse proxy. You will need to configure it with your domain and set up SSL. A template is provided in `monitoring/nginx/conf.d/omnipath.conf.template`. Copy this to `omnipath.conf`, edit it with your domain, and then use Certbot to obtain an SSL certificate.

5.  **Verify**: Check that all services are running and healthy. Access your domain to ensure the API is reachable.

    ```bash
    docker-compose -f docker-compose.production.yml ps
    curl https://your-domain.com/health
    ```

## Option 2: Kubernetes Deployment (Production)

This method is for deploying to a Kubernetes cluster for high availability and scalability.

### Prerequisites

-   A running Kubernetes cluster.
-   `kubectl` configured to access the cluster.
-   A container registry (e.g., Docker Hub, AWS ECR) where you can push the OmniPath image.

### Deployment Steps

1.  **Build and Push Image**: Build the production Docker image and push it to your container registry.

    ```bash
    docker build -t your-registry/omnipath-backend:latest -f Dockerfile.production .
    docker push your-registry/omnipath-backend:latest
    ```

2.  **Create Secrets**: Create a `secrets.yaml` file from the `k8s/secrets.yaml.template`. This file contains all the sensitive environment variables. Base64-encode each value before adding it to the file.

    ```bash
    # Example for one secret
    echo -n 'your-super-secret-value' | base64
    ```

    Apply the secrets to your cluster:

    ```bash
    kubectl apply -f k8s/secrets.yaml
    ```

3.  **Apply Manifests**: Apply the Kubernetes manifests from the `k8s/` directory in the correct order.

    ```bash
    # Network policies for security
    kubectl apply -f k8s/network-policy.yaml

    # The main application deployment
    kubectl apply -f k8s/deployment.yaml

    # Expose the service via an Ingress controller
    kubectl apply -f k8s/ingress.yaml
    ```

4.  **Verify Deployment**: Check the status of the deployment to ensure all pods are running and healthy.

    ```bash
    kubectl get pods -l app=omnipath-backend
    kubectl describe deployment omnipath-backend
    ```

This runbook provides the essential steps for both deployment methods. Refer to the specific configuration files and templates in the repository for more detailed settings.
