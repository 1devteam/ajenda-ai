"""
Prometheus Metrics Integration for Omnipath v3.0
Synchronized with Grafana dashboards for Mission, LLM, and Agent Economy tracking.

Built with Pride for Obex Blackvault.
"""

import logging
from typing import Optional
from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, REGISTRY
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
        
        # --- Mission Metrics ---
        # Counter for total missions by status and complexity
        # status: PENDING, RUNNING, COMPLETED, FAILED, REJECTED
        self.missions_total = Counter(
            'omnipath_missions_total',
            'Total number of missions executed',
            ['status', 'complexity']
        )
        
        # Histogram for mission duration
        self.mission_duration = Histogram(
            'omnipath_mission_duration_seconds',
            'Mission execution duration in seconds',
            ['complexity'],
            buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800)
        )
        
        # Gauge for currently active missions
        self.missions_active = Gauge(
            'omnipath_active_missions',
            'Number of currently active missions'
        )
        
        # --- Agent Metrics ---
        # Counter for agent invocations
        self.agent_invocations = Counter(
            'omnipath_agent_invocations_total',
            'Total agent invocations',
            ['agent_type', 'model']
        )
        
        # Counter for agent errors
        self.agent_errors = Counter(
            'omnipath_agent_errors_total',
            'Total agent execution errors',
            ['agent_type', 'error_type']
        )

        # Gauge for current agent status (1 for active state, 0 otherwise)
        self.agent_status = Gauge(
            'omnipath_agent_status',
            'Current status of an agent',
            ['agent_type', 'status']
        )
        
        # --- Economy Metrics ---
        # Counter for credits earned
        self.credits_earned = Counter(
            'omnipath_credits_earned_total',
            'Total credits earned by agents',
            ['agent_id', 'resource_type']
        )
        
        # Counter for credits spent
        self.credits_spent = Counter(
            'omnipath_credits_spent_total',
            'Total credits spent by agents',
            ['agent_id', 'resource_type']
        )
        
        # Gauge for current agent credit balance
        self.agent_balance = Gauge(
            'omnipath_agent_balance',
            'Current credit balance per agent',
            ['agent_id']
        )
        
        # --- LLM API Metrics ---
        # Counter for total LLM API calls
        self.llm_api_calls = Counter(
            'omnipath_llm_api_calls_total',
            'Total LLM API calls',
            ['provider', 'model']
        )
        
        # Counter for tokens used
        self.llm_tokens_used = Counter(
            'omnipath_llm_tokens_used_total',
            'Total tokens used',
            ['provider', 'model', 'type']  # type: prompt, completion
        )
        
        # Counter for total LLM cost in USD
        self.llm_cost = Counter(
            'omnipath_llm_cost_total',
            'Total LLM API cost in USD',
            ['provider', 'model']
        )
        
        # Histogram for LLM call latency
        self.llm_latency = Histogram(
            'omnipath_llm_latency_seconds',
            'LLM API call latency',
            ['provider', 'model'],
            buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
        )
        
        # --- System Metrics ---
        # Counter for HTTP requests
        self.http_requests = Counter(
            'omnipath_http_requests_total',
            'Total HTTP requests',
            ['method', 'endpoint', 'status']
        )
        
        # Histogram for HTTP request duration
        self.http_request_duration = Histogram(
            'omnipath_http_request_duration_seconds',
            'HTTP request duration',
            ['method', 'endpoint'],
            buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0)
        )
        
        # Counter for internal system errors
        self.system_errors = Counter(
            'omnipath_system_errors_total',
            'Total system errors',
            ['error_type']
        )

        # Counter for user logins
        self.user_logins = Counter(
            'omnipath_user_logins_total',
            'Total user logins',
            ['tenant_id']
        )

        # Counter for rate limit exceeded events
        self.rate_limit_exceeded = Counter(
            'omnipath_rate_limit_exceeded_total',
            'Total rate limit exceed events',
            ['identifier']
        )

        # Counter for NATS message throughput
        self.nats_messages = Counter(
            'omnipath_nats_messages_total',
            'Total NATS messages processed',
            ['subject', 'direction'] # direction: pub, sub
        )
        
        # Gauge for application info
        self.app_info = Info(
            'omnipath_app',
            'Application information'
        )
        
        logger.info("Prometheus metrics initialized")
    
    def record_mission_created(self, complexity: str, priority: str = "1"):
        """Record mission creation (PENDING status)"""
        if self.enabled:
            self.missions_total.labels(status="PENDING", complexity=complexity).inc()

    def record_mission_start(self, complexity: str = "simple"):
        """Record mission start (RUNNING status)"""
        if self.enabled:
            self.missions_active.inc()
            self.missions_total.labels(status="RUNNING", complexity=complexity).inc()
    
    def record_mission_complete(
        self,
        status: str,
        complexity: str,
        duration_seconds: float
    ):
        """Record terminal mission status (COMPLETED, FAILED, REJECTED) and duration"""
        if self.enabled:
            # Normalize status for dashboard expectations
            status_upper = status.upper()
            if status_upper in ["SUCCESS", "COMPLETED"]:
                norm_status = "COMPLETED"
            elif status_upper in ["FAILURE", "FAILED", "ERROR"]:
                norm_status = "FAILED"
            elif status_upper == "REJECTED":
                norm_status = "REJECTED"
            else:
                norm_status = status_upper
                
            self.missions_total.labels(status=norm_status, complexity=complexity).inc()
            self.mission_duration.labels(complexity=complexity).observe(duration_seconds)
            self.missions_active.dec()
    
    def record_agent_invocation(self, agent_type: str, model: str):
        """Record agent being invoked"""
        if self.enabled:
            self.agent_invocations.labels(agent_type=agent_type, model=model).inc()
    
    def record_agent_error(self, agent_type: str, error_type: str):
        """Record agent execution error"""
        if self.enabled:
            self.agent_errors.labels(agent_type=agent_type, error_type=error_type).inc()

    def record_agent_status(self, agent_type: str, status: str):
        """
        Record current agent status.
        status: idle, running, completed, failed
        """
        if self.enabled:
            # Reset all statuses for this agent type first to ensure only one is active
            for s in ["idle", "running", "completed", "failed"]:
                self.agent_status.labels(agent_type=agent_type, status=s).set(0)
            self.agent_status.labels(agent_type=agent_type, status=status.lower()).set(1)
    
    def record_credits_earned(self, agent_id: str, resource_type: str, amount: float):
        """Record credits earned/rewarded"""
        if self.enabled:
            self.credits_earned.labels(agent_id=agent_id, resource_type=resource_type).inc(amount)
    
    def record_credits_spent(self, agent_id: str, resource_type: str, amount: float):
        """Record credits spent/consumed"""
        if self.enabled:
            self.credits_spent.labels(agent_id=agent_id, resource_type=resource_type).inc(amount)
    
    def update_agent_balance(self, agent_id: str, balance: float):
        """Update current agent credit balance"""
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
        """Record comprehensive LLM call metrics"""
        if self.enabled:
            self.llm_api_calls.labels(provider=provider, model=model).inc()
            self.llm_tokens_used.labels(
                provider=provider,
                model=model,
                type="prompt"
            ).inc(prompt_tokens)
            self.llm_tokens_used.labels(
                provider=provider,
                model=model,
                type="completion"
            ).inc(completion_tokens)
            self.llm_cost.labels(provider=provider, model=model).inc(cost_usd)
            self.llm_latency.labels(provider=provider, model=model).observe(latency_seconds)
    
    def record_http_request(self, method: str, endpoint: str, status: int, duration_seconds: float):
        """Record HTTP request metrics"""
        if self.enabled:
            self.http_requests.labels(method=method, endpoint=endpoint, status=str(status)).inc()
            self.http_request_duration.labels(method=method, endpoint=endpoint).observe(duration_seconds)
    
    def record_system_error(self, error_type: str):
        """Record internal system error"""
        if self.enabled:
            self.system_errors.labels(error_type=error_type).inc()

    def record_user_login(self, tenant_id: str):
        """Record user login event"""
        if self.enabled:
            self.user_logins.labels(tenant_id=tenant_id).inc()

    def record_rate_limit_exceeded(self, identifier: str):
        """Record rate limit event"""
        if self.enabled:
            self.rate_limit_exceeded.labels(identifier=identifier).inc()

    def record_nats_message(self, subject: str, direction: str):
        """Record NATS message throughput"""
        if self.enabled:
            self.nats_messages.labels(subject=subject, direction=direction).inc()
    
    def set_app_info(self, version: str, environment: str):
        """Set application metadata info"""
        if self.enabled:
            self.app_info.info({'version': version, 'environment': environment})
    
    def get_metrics(self) -> bytes:
        """Generate metrics in Prometheus format"""
        if not self.enabled:
            return b""
        return generate_latest(REGISTRY)


# Global metrics singleton
metrics = PrometheusMetrics()

def get_metrics() -> PrometheusMetrics:
    """Get the global PrometheusMetrics instance"""
    return metrics

def metrics_endpoint():
    """FastAPI endpoint for Prometheus scraping"""
    return Response(
        content=metrics.get_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8"
    )
