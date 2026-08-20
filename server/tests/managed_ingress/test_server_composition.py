"""Local-only production ingress composition without changing public routes."""

from fastapi.testclient import TestClient


def test_public_app_constructs_no_managed_ingress(server_module):
    app = server_module.create_app(
        enable_local_routes=False, enable_managed_ingress=False
    )

    assert app.state.task_runtime is None
    assert app.state.work_store is None
    assert app.state.managed_ingress is None
    assert app.state.work_delivery is None
    assert not hasattr(app.state, "agent")


def test_local_app_owns_agent_ingress_and_dedicated_listener(
    server_module, monkeypatch
):
    events = []

    class FakeListener:
        def __init__(self, _app, **_kwargs):
            self.local_url = "http://127.0.0.1:8001"

        async def start(self):
            events.append("listener.started")

        async def close(self):
            events.append("listener.closed")

    class FakeTunnel:
        async def start(self, _local_url):
            raise AssertionError("ngrok must not start before an Agent is requested")

        async def status(self):
            raise AssertionError("ngrok must not be polled before Agent preparation")

        async def close(self):
            events.append("tunnel.closed")

    class FakeDelivery:
        def __init__(self, *, store, sessions, workspace):
            self.store = store
            self.sessions = sessions
            self.workspace = workspace
            self.notifications = []

        async def start(self):
            events.append("delivery.started")

        def notify(self, work_id):
            self.notifications.append(work_id)

        async def close(self):
            events.append("delivery.closed")

    monkeypatch.setattr(server_module, "UvicornListener", FakeListener)
    monkeypatch.setattr(server_module, "NgrokCliTunnel", FakeTunnel)
    monkeypatch.setattr(server_module, "WorkDeliveryCoordinator", FakeDelivery)
    app = server_module.create_app(
        enable_local_routes=True, enable_managed_ingress=True
    )

    with TestClient(app) as client:
        assert client.get("/get_config").status_code == 200
        assert app.state.task_runtime is not None
        assert app.state.work_store is not None
        assert app.state.managed_ingress is not None
        assert app.state.work_delivery is not None
        assert app.state.agent.work_bridge is app.state.managed_ingress
        assert app.state.work_delivery.store is app.state.work_store
        assert app.state.work_delivery.sessions is app.state.agent
        assert app.state.work_delivery.workspace is app.state.managed_ingress
        assert events == ["delivery.started", "listener.started"]
        assert client.get("/mcp/").status_code == 404

    assert events == [
        "delivery.started",
        "listener.started",
        "delivery.closed",
        "tunnel.closed",
        "listener.closed",
    ]
