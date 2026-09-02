"""Drift guards for customer frontend deployment artifacts."""

from __future__ import annotations

from pathlib import Path

COMPOSE_FILE = Path("deploy/compose/docker-compose.prod.yml")
DEV_COMPOSE_FILE = Path("docker-compose.yml")
FRONTEND_DOCKERFILE = Path("deploy/docker/frontend.Dockerfile")
COMPOSE_NGINX = Path("deploy/nginx/frontend.compose.conf")
K8S_NGINX = Path("deploy/nginx/frontend.k8s.conf")
K8S_INGRESS = Path("deploy/k8s/ingress.yaml")
K8S_FRONTEND_DEPLOYMENT = Path("deploy/k8s/frontend-deployment.yaml")
K8S_FRONTEND_SERVICE = Path("deploy/k8s/frontend-service.yaml")
RELEASE_WORKFLOW = Path(".github/workflows/release.yml")
CI_WORKFLOW = Path(".github/workflows/ci.yml")
STAGING_PROOF_SCRIPT = Path("deploy/scripts/paid-customer-loop-staging-proof.sh")
STRIPE_BOOTSTRAP_SCRIPT = Path("deploy/scripts/stripe-staging-bootstrap.sh")
STRIPE_BILLING_PROOF_SCRIPT = Path("deploy/scripts/stripe-billing-staging-proof.sh")
STAGING_RUNBOOK = Path("ops/runbooks/paid-customer-loop-staging.md")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_compose_declares_frontend_service() -> None:
    compose = _read(COMPOSE_FILE)
    assert "frontend:" in compose
    assert "deploy/docker/frontend.Dockerfile" in compose
    assert '"8080:80"' in compose or "8080:80" in compose


def test_dev_compose_declares_frontend_service() -> None:
    compose = _read(DEV_COMPOSE_FILE)
    assert "frontend:" in compose
    assert "deploy/docker/frontend.Dockerfile" in compose
    assert '"8080:80"' in compose or "8080:80" in compose


def test_frontend_dockerfile_builds_vite_app_and_serves_with_nginx() -> None:
    dockerfile = _read(FRONTEND_DOCKERFILE)
    assert "npm run build" in dockerfile
    assert "nginx:1.27-alpine" in dockerfile
    assert "VITE_API_BASE_URL=" in dockerfile
    assert "rm -f .env" in dockerfile
    # Credential-shaped keys must never appear in image ENV metadata.
    assert "VITE_DEFAULT_API_KEY" not in dockerfile
    assert "VITE_DEFAULT_TENANT_ID" not in dockerfile


def test_compose_nginx_proxies_api_paths() -> None:
    nginx = _read(COMPOSE_NGINX)
    assert "location /v1/" in nginx
    assert "resolver 127.0.0.11" in nginx
    assert "set $api_upstream http://api:8000" in nginx
    assert "proxy_pass $api_upstream" in nginx
    assert "proxy_set_header Authorization" in nginx
    assert "proxy_set_header X-Tenant-Id" in nginx
    assert "try_files $uri $uri/ /index.html" in nginx


def test_k8s_nginx_serves_spa_only() -> None:
    nginx = _read(K8S_NGINX)
    assert "try_files $uri $uri/ /index.html" in nginx
    assert "proxy_pass" not in nginx


def test_k8s_ingress_routes_api_and_frontend() -> None:
    ingress = _read(K8S_INGRESS)
    assert "name: ajenda-api" in ingress
    assert "name: ajenda-frontend" in ingress
    assert "path: /v1" in ingress


def test_k8s_frontend_manifests_exist() -> None:
    deployment = _read(K8S_FRONTEND_DEPLOYMENT)
    service = _read(K8S_FRONTEND_SERVICE)
    assert "ajenda-frontend" in deployment
    assert "ajenda-frontend" in service
    assert "component: frontend" in deployment


def test_release_workflow_publishes_frontend_image() -> None:
    workflow = _read(RELEASE_WORKFLOW)
    assert "deploy/docker/frontend.Dockerfile" in workflow
    assert "Build and push frontend image" in workflow
    assert "frontend_tags=" in workflow
    assert "${IMAGE_NAME}-frontend:" in workflow or "IMAGE_NAME}-frontend" in workflow
    assert "NGINX_CONF=deploy/nginx/frontend.k8s.conf" in workflow


def test_ci_docker_build_matrix_includes_frontend_image() -> None:
    workflow = _read(CI_WORKFLOW)
    assert "deploy/docker/frontend.Dockerfile" in workflow
    assert "ajenda-ai-frontend" in workflow
    assert "NGINX_CONF=deploy/nginx/frontend.k8s.conf" in workflow


def test_k8s_frontend_deployment_uses_versioned_ghcr_image() -> None:
    deployment = _read(K8S_FRONTEND_DEPLOYMENT)
    image_lines = [line.strip() for line in deployment.splitlines() if line.strip().startswith("image:")]
    assert image_lines
    image_ref = image_lines[0].removeprefix("image:").strip()
    assert image_ref.startswith("ghcr.io/")
    assert "-frontend:" in image_ref
    assert not image_ref.endswith(":latest")


def test_staging_runbook_and_proof_script_align() -> None:
    runbook = _read(STAGING_RUNBOOK)
    script = _read(STAGING_PROOF_SCRIPT)
    assert STAGING_PROOF_SCRIPT.name in runbook
    assert "/v1/onboarding/signup" in script
    assert "/v1/onboarding/verify-email" in script
    assert "/v1/onboarding/promote-bootstrap-key" in script
    assert "/v1/account/me" in script
    assert "/v1/account/billing" in script
    assert 'id="root"' in script


def test_stripe_staging_scripts_exist_and_reference_billing_paths() -> None:
    bootstrap = _read(STRIPE_BOOTSTRAP_SCRIPT)
    billing_proof = _read(STRIPE_BILLING_PROOF_SCRIPT)
    runbook = _read(STAGING_RUNBOOK)
    assert STRIPE_BOOTSTRAP_SCRIPT.name in runbook
    assert STRIPE_BILLING_PROOF_SCRIPT.name in runbook
    assert "/v1/billing/webhook/stripe" in billing_proof
    assert "/v1/ability-runtime/proofs/calendar-read" in billing_proof
    assert "stripe_webhook_proof_ready" in bootstrap
