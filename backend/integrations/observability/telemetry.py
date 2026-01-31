"""
OpenTelemetry Telemetry - Full Implementation for v5.0
Distributed tracing and observability
"""
import logging
from typing import Optional
from contextlib import contextmanager

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    logging.warning("OpenTelemetry not installed. Install with: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp")


logger = logging.getLogger(__name__)


class TelemetryManager:
    """
    OpenTelemetry Telemetry Manager
    
    Think of this as a GPS tracker for your requests:
    - Tracks every request through your system
    - Shows where time is spent
    - Helps find bottlenecks and errors
    - Visualizes the flow in Jaeger
    """
    
    def __init__(self, service_name: str = "omnipath", 
                 otlp_endpoint: Optional[str] = None):
        self.service_name = service_name
        self.otlp_endpoint = otlp_endpoint or "http://localhost:4317"
        self.tracer_provider: Optional[TracerProvider] = None
        self.tracer = None
        self._initialized = False
        
        if not OTEL_AVAILABLE:
            logger.warning("OpenTelemetry not available - tracing disabled")
    
    def initialize(self):
        """
        Initialize OpenTelemetry tracing
        
        Sets up the connection to Jaeger for viewing traces
        """
        if not OTEL_AVAILABLE:
            logger.info("OpenTelemetry not available - running without tracing")
            self._initialized = True
            return
        
        try:
            # Create resource with service name
            resource = Resource(attributes={
                SERVICE_NAME: self.service_name
            })
            
            # Create tracer provider
            self.tracer_provider = TracerProvider(resource=resource)
            
            # Create OTLP exporter
            otlp_exporter = OTLPSpanExporter(
                endpoint=self.otlp_endpoint,
                insecure=True  # Use insecure for local development
            )
            
            # Add span processor
            span_processor = BatchSpanProcessor(otlp_exporter)
            self.tracer_provider.add_span_processor(span_processor)
            
            # Set global tracer provider
            trace.set_tracer_provider(self.tracer_provider)
            
            # Get tracer
            self.tracer = trace.get_tracer(__name__)
            
            self._initialized = True
            logger.info(f"OpenTelemetry initialized - sending traces to {self.otlp_endpoint}")
            
        except Exception as e:
            logger.error(f"Failed to initialize OpenTelemetry: {e}")
            logger.info("Continuing without tracing")
            self._initialized = True
    
    def instrument_fastapi(self, app):
        """
        Instrument FastAPI application for automatic tracing
        
        This automatically tracks all API requests
        """
        if not OTEL_AVAILABLE or not self._initialized:
            logger.debug("Skipping FastAPI instrumentation - OpenTelemetry not available")
            return
        
        try:
            FastAPIInstrumentor.instrument_app(app)
            logger.info("FastAPI instrumented for tracing")
        except Exception as e:
            logger.error(f"Failed to instrument FastAPI: {e}")
    
    @contextmanager
    def trace_span(self, name: str, attributes: dict = None):
        """
        Create a trace span for custom operations
        
        Use this to track specific operations in your code
        
        Example:
            with telemetry.trace_span("execute_mission", {"mission_id": "123"}):
                # Your code here
                result = execute_mission()
        """
        if not OTEL_AVAILABLE or not self.tracer:
            # No-op context manager when tracing is disabled
            yield None
            return
        
        try:
            with self.tracer.start_as_current_span(name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, str(value))
                yield span
        except Exception as e:
            logger.error(f"Error in trace span: {e}")
            yield None
    
    def add_event(self, span, name: str, attributes: dict = None):
        """
        Add an event to the current span
        
        Like adding a note to the GPS tracker: "stopped here for gas"
        """
        if span and OTEL_AVAILABLE:
            try:
                span.add_event(name, attributes=attributes or {})
            except Exception as e:
                logger.error(f"Error adding event: {e}")
    
    def set_span_attribute(self, span, key: str, value):
        """
        Set an attribute on the current span
        
        Adds extra information to the trace
        """
        if span and OTEL_AVAILABLE:
            try:
                span.set_attribute(key, str(value))
            except Exception as e:
                logger.error(f"Error setting attribute: {e}")
    
    def record_exception(self, span, exception: Exception):
        """
        Record an exception in the current span
        
        Marks the trace as having an error
        """
        if span and OTEL_AVAILABLE:
            try:
                span.record_exception(exception)
                span.set_status(trace.Status(trace.StatusCode.ERROR))
            except Exception as e:
                logger.error(f"Error recording exception: {e}")
    
    def shutdown(self):
        """
        Shutdown telemetry and flush remaining spans
        
        Call this on application shutdown
        """
        if self.tracer_provider and OTEL_AVAILABLE:
            try:
                self.tracer_provider.shutdown()
                logger.info("OpenTelemetry shutdown complete")
            except Exception as e:
                logger.error(f"Error shutting down OpenTelemetry: {e}")


# Global telemetry manager
telemetry = TelemetryManager()


def get_telemetry() -> TelemetryManager:
    """
    Get the global telemetry manager
    
    Use this in your code to access telemetry
    """
    if not telemetry._initialized:
        telemetry.initialize()
    return telemetry


# Backward compatibility with old stub interface
def get_tracer(name: str = "omnipath"):
    """Get tracer (backward compatible)"""
    tel = get_telemetry()
    return tel.tracer if tel.tracer else None


def get_meter(name: str = "omnipath"):
    """Get meter (stub - not implemented yet)"""
    logger.debug("Meter not implemented yet - use Prometheus metrics instead")
    return None
