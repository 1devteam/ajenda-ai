from backend.main import create_app



def test_create_app_bootstraps_without_route_to_main_coupling() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/readiness" in paths
