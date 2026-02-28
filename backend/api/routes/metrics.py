"""
Prometheus Metrics Endpoint
Exposes metrics for monitoring and alerting
"""

from fastapi import APIRouter
from backend.integrations.observability.prometheus_metrics import metrics_endpoint

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics():
    """
    Prometheus metrics endpoint

    Exposes all Prometheus metrics for scraping
    """
    return metrics_endpoint()
