"""
Structured Logging Configuration for Omnipath v5.0
Implements JSON-structured logging with context and correlation IDs

Built with Pride for Obex Blackvault
"""

import logging
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, Optional
from contextvars import ContextVar
from pythonjsonlogger import jsonlogger


# Context variables for request tracking
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
tenant_id_var: ContextVar[Optional[str]] = ContextVar("tenant_id", default=None)


class OmnipathJsonFormatter(jsonlogger.JsonFormatter):
    """
    Custom JSON formatter that adds context information to log records
    """

    def add_fields(
        self,
        log_record: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Dict[str, Any],
    ) -> None:
        """Add custom fields to log record"""
        super().add_fields(log_record, record, message_dict)

        # Add timestamp
        log_record["timestamp"] = datetime.utcnow().isoformat() + "Z"

        # Add service information
        log_record["service"] = "omnipath"
        log_record["version"] = "5.0.0"
        log_record["environment"] = self.get_environment()

        # Add log level
        log_record["level"] = record.levelname
        log_record["logger"] = record.name

        # Add source location
        log_record["source"] = {
            "file": record.pathname,
            "line": record.lineno,
            "function": record.funcName,
        }

        # Add context information
        request_id = request_id_var.get()
        if request_id:
            log_record["request_id"] = request_id

        user_id = user_id_var.get()
        if user_id:
            log_record["user_id"] = user_id

        tenant_id = tenant_id_var.get()
        if tenant_id:
            log_record["tenant_id"] = tenant_id

        # Add exception information if present
        if record.exc_info:
            log_record["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

    @staticmethod
    def get_environment() -> str:
        """Get current environment from config"""
        import os

        return os.getenv("ENVIRONMENT", "development")


def setup_logging(
    level: str = "INFO", json_logs: bool = True, log_file: Optional[str] = None
) -> None:
    """
    Configure structured logging for the application

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_logs: Whether to use JSON formatting
        log_file: Optional file path for file logging
    """
    # Remove existing handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Set log level
    log_level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    if json_logs:
        # JSON formatter for structured logs
        formatter = OmnipathJsonFormatter("%(timestamp)s %(level)s %(name)s %(message)s")
    else:
        # Human-readable formatter for development
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Set levels for noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


def set_request_context(
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> None:
    """
    Set context variables for the current request

    Args:
        request_id: Unique request identifier
        user_id: User identifier
        tenant_id: Tenant identifier
    """
    if request_id:
        request_id_var.set(request_id)
    if user_id:
        user_id_var.set(user_id)
    if tenant_id:
        tenant_id_var.set(tenant_id)


def clear_request_context() -> None:
    """Clear all request context variables"""
    request_id_var.set(None)
    user_id_var.set(None)
    tenant_id_var.set(None)


class LoggerMixin:
    """
    Mixin class that provides logging capabilities to any class
    """

    @property
    def logger(self) -> logging.Logger:
        """Get logger for this class"""
        if not hasattr(self, "_logger"):
            self._logger = get_logger(self.__class__.__name__)
        return self._logger

    def log_info(self, message: str, **kwargs) -> None:
        """Log info message with optional context"""
        self.logger.info(message, extra=kwargs)

    def log_warning(self, message: str, **kwargs) -> None:
        """Log warning message with optional context"""
        self.logger.warning(message, extra=kwargs)

    def log_error(self, message: str, exc_info: bool = False, **kwargs) -> None:
        """Log error message with optional exception info"""
        self.logger.error(message, exc_info=exc_info, extra=kwargs)

    def log_debug(self, message: str, **kwargs) -> None:
        """Log debug message with optional context"""
        self.logger.debug(message, extra=kwargs)


# Example usage functions
def log_api_request(method: str, path: str, status_code: int, duration_ms: float, **kwargs) -> None:
    """
    Log API request with structured data

    Args:
        method: HTTP method
        path: Request path
        status_code: Response status code
        duration_ms: Request duration in milliseconds
        **kwargs: Additional context
    """
    logger = get_logger("omnipath.api")
    logger.info(
        f"{method} {path} {status_code}",
        extra={
            "event_type": "api_request",
            "http": {"method": method, "path": path, "status_code": status_code},
            "duration_ms": duration_ms,
            **kwargs,
        },
    )


def log_mission_event(event_type: str, mission_id: str, agent_id: str, **kwargs) -> None:
    """
    Log mission-related event

    Args:
        event_type: Type of event (started, completed, failed, etc.)
        mission_id: Mission identifier
        agent_id: Agent identifier
        **kwargs: Additional context
    """
    logger = get_logger("omnipath.missions")
    logger.info(
        f"Mission {event_type}: {mission_id}",
        extra={
            "event_type": f"mission_{event_type}",
            "mission_id": mission_id,
            "agent_id": agent_id,
            **kwargs,
        },
    )


def log_llm_call(
    provider: str,
    model: str,
    tokens_used: int,
    duration_ms: float,
    cost: float,
    **kwargs,
) -> None:
    """
    Log LLM API call with metrics

    Args:
        provider: LLM provider (openai, anthropic, etc.)
        model: Model name
        tokens_used: Number of tokens used
        duration_ms: Call duration in milliseconds
        cost: Cost in USD
        **kwargs: Additional context
    """
    logger = get_logger("omnipath.llm")
    logger.info(
        f"LLM call: {provider}/{model}",
        extra={
            "event_type": "llm_call",
            "llm": {
                "provider": provider,
                "model": model,
                "tokens_used": tokens_used,
                "cost_usd": cost,
            },
            "duration_ms": duration_ms,
            **kwargs,
        },
    )


def log_economy_transaction(
    transaction_type: str, agent_id: str, amount: float, balance_after: float, **kwargs
) -> None:
    """
    Log economy transaction

    Args:
        transaction_type: Type of transaction (earn, spend, transfer)
        agent_id: Agent identifier
        amount: Transaction amount
        balance_after: Agent balance after transaction
        **kwargs: Additional context
    """
    logger = get_logger("omnipath.economy")
    logger.info(
        f"Economy transaction: {transaction_type}",
        extra={
            "event_type": f"economy_{transaction_type}",
            "agent_id": agent_id,
            "transaction": {
                "type": transaction_type,
                "amount": amount,
                "balance_after": balance_after,
            },
            **kwargs,
        },
    )


def log_performance_metric(metric_name: str, value: float, unit: str, **kwargs) -> None:
    """
    Log performance metric

    Args:
        metric_name: Name of the metric
        value: Metric value
        unit: Unit of measurement
        **kwargs: Additional context
    """
    logger = get_logger("omnipath.performance")
    logger.info(
        f"Performance metric: {metric_name}",
        extra={
            "event_type": "performance_metric",
            "metric": {"name": metric_name, "value": value, "unit": unit},
            **kwargs,
        },
    )
