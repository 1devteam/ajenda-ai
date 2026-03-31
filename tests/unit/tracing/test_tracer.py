from backend.tracing.tracer import Tracer


def test_tracer_returns_trace_context() -> None:
    context = Tracer().new_context()
    assert context.trace_id
