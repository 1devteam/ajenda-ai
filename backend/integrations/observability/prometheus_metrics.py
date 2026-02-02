"""
Prometheus Metrics for Omnipath v5.0
Real-time metrics collection for monitoring and alerting
"""
import logging
from typing import Optional
from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, REGISTRY
from prometheus_client import CollectorRegistry
from fastapi import Response

logger = logging.getLogger(__name__)


class PrometheusMetrics:
    """
    Prometheus metrics manager for Omnipath
    
    Tracks:
    - Mission execution (count, duration, success rate)
    - Agent invocations (by type, model)
    - Economy transactions (credits earned/spent)
    - LLM API calls (by provider, cost)
    - System health (uptime, errors)
    """
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        
        if not enabled:
            logger.info("Prometheus metrics disabled")
            return
        
        # Mission Metrics
        self.missions_total = Counter(
            'omnipath_missions_total',
            'Total number of missions executed',
            ['status', 'complexity']
        )
        
        self.mission_duration = Histogram(
            'omnipath_mission_duration_seconds',
            'Mission execution duration in seconds',
            ['complexity'],
            buckets=(1, 5, 10, 30, 60, 120, 300, 600)
        )
        
        self.missions_active = Gauge(
            'omnipath_missions_active',
            'Number of currently active missions'
        )
        
        # Agent Metrics
        self.agent_invocations = Counter(
            'omnipath_agent_invocations_total',
            'Total agent invocations',
            ['agent_type', 'model']
        )
        
        self.agent_errors = Counter(
            'omnipath_agent_errors_total',
            'Total agent execution errors',
            ['agent_type', 'error_type']
        )
        
        # Economy Metrics
        self.credits_earned = Counter(
            'omnipath_credits_earned_total',
            'Total credits earned by agents',
            ['agent_id', 'resource_type']
        )
        
        self.credits_spent = Counter(
            'omnipath_credits_spent_total',
            'Total credits spent by agents',
            ['agent_id', 'resource_type']
        )
        
        self.agent_balance = Gauge(
            'omnipath_agent_balance_credits',
            'Current credit balance per agent',
            ['agent_id']
        )
        
        # LLM API Metrics
        self.llm_calls = Counter(
            'omnipath_llm_calls_total',
            'Total LLM API calls',
            ['provider', 'model']
        )
        
        self.llm_tokens = Counter(
            'omnipath_llm_tokens_total',
            'Total tokens used',
            ['provider', 'model', 'type']  # type: prompt/completion
        )
        
        self.llm_cost = Counter(
            'omnipath_llm_cost_usd_total',
            'Total LLM API cost in USD',
            ['provider', 'model']
        )
        
        self.llm_latency = Histogram(
            'omnipath_llm_latency_seconds',
            'LLM API call latency',
            ['provider', 'model'],
            buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
        )
        
        # System Metrics
        self.http_requests = Counter(
            'omnipath_http_requests_total',
            'Total HTTP requests',
            ['method', 'endpoint', 'status']
        )
        
        self.http_request_duration = Histogram(
            'omnipath_http_request_duration_seconds',
            'HTTP request duration',
            ['method', 'endpoint'],
            buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0)
        )
        
        self.system_errors = Counter(
            'omnipath_system_errors_total',
            'Total system errors',
            ['error_type']
        )
        
        # Application Info
        self.app_info = Info(
            'omnipath_app',
            'Application information'
        )
        
        logger.info("Prometheus metrics initialized")
    
    def record_mission_start(self, complexity: str = "simple"):
        """Record mission start"""
        if self.enabled:
            self.missions_active.inc()
    
    def record_mission_complete(
        self,
        status: str,
        complexity: str,
        duration_seconds: float
    ):
        """Record mission completion"""
        if self.enabled:
            self.missions_total.labels(status=status, complexity=complexity).inc()
            self.mission_duration.labels(complexity=complexity).observe(duration_seconds)
            self.missions_active.dec()
    
    def record_agent_invocation(self, agent_type: str, model: str):
        """Record agent invocation"""
        if self.enabled:
            self.agent_invocations.labels(agent_type=agent_type, model=model).inc()
    
    def record_agent_error(self, agent_type: str, error_type: str):
        """Record agent error"""
        if self.enabled:
            self.agent_errors.labels(agent_type=agent_type, error_type=error_type).inc()
    
    def record_credits_earned(
        self,
        agent_id: str,
        resource_type: str,
        amount: float
    ):
        """Record credits earned"""
        if self.enabled:
            self.credits_earned.labels(
                agent_id=agent_id,
                resource_type=resource_type
            ).inc(amount)
    
    def record_credits_spent(
        self,
        agent_id: str,
        resource_type: str,
        amount: float
    ):
        """Record credits spent"""
        if self.enabled:
            self.credits_spent.labels(
                agent_id=agent_id,
                resource_type=resource_type
            ).inc(amount)
    
    def update_agent_balance(self, agent_id: str, balance: float):
        """Update agent balance gauge"""
        if self.enabled:
            self.agent_balance.labels(agent_id=agent_id).set(balance)
    
    def record_llm_call(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        latency_seconds: float
    ):
        """Record LLM API call metrics"""
        if self.enabled:
            self.llm_calls.labels(provider=provider, model=model).inc()
            self.llm_tokens.labels(
                provider=provider,
                model=model,
                type="prompt"
            ).inc(prompt_tokens)
            self.llm_tokens.labels(
                provider=provider,
                model=model,
                type="completion"
            ).inc(completion_tokens)
            self.llm_cost.labels(provider=provider, model=model).inc(cost_usd)
            self.llm_latency.labels(provider=provider, model=model).observe(latency_seconds)
    
    def record_http_request(
        self,
        method: str,
        endpoint: str,
        status: int,
        duration_seconds: float
    ):
        """Record HTTP request metrics"""
        if self.enabled:
            self.http_requests.labels(
                method=method,
                endpoint=endpoint,
                status=str(status)
            ).inc()
            self.http_request_duration.labels(
                method=method,
                endpoint=endpoint
            ).observe(duration_seconds)
    
    def record_system_error(self, error_type: str):
        """Record system error"""
        if self.enabled:
            self.system_errors.labels(error_type=error_type).inc()
    
    def set_app_info(self, version: str, environment: str):
        """Set application info"""
        if self.enabled:
            self.app_info.info({
                'version': version,
                'environment': environment
            })
    
    def get_metrics(self) -> bytes:
        """Get metrics in Prometheus format"""
        if not self.enabled:
            return b""
        return generate_latest(REGISTRY)


# Global metrics instance
metrics = PrometheusMetrics()


def get_metrics() -> PrometheusMetrics:
    """Get global metrics instance"""
    return metrics


def metrics_endpoint():
    """FastAPI endpoint for Prometheus metrics"""
    return Response(
        content=metrics.get_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8"
    )
