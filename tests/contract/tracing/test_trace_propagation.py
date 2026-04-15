from backend.tracing.tracer import Tracer


def test_trace_propagation_smoke() -> None:
    context = Tracer().new_context()
    assert context.trace_id is not None
