"""Ordinary FastAPI startup must not launch the optional ACP runtime."""

import importlib
import sys

from fastapi.testclient import TestClient


class FakeStartupRuntime:
    def __init__(self) -> None:
        self.start_calls = 0
        self.close_calls = 0

    async def start(self):
        self.start_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


def test_saved_workspace_does_not_open_acp_during_ordinary_app_startup(
    server_module, tmp_path
):
    project = tmp_path / "saved-project"
    project.mkdir()
    server_module.workspace_service.select(str(project))
    runtime = FakeStartupRuntime()
    server_module.local_runtime = runtime

    with TestClient(server_module.app):
        pass

    assert runtime.start_calls == 0
    assert runtime.close_calls == 1


def test_local_routes_enabled_requires_explicit_opt_in(server_module):
    assert server_module.local_routes_enabled({"VOICE_ACP_LOCAL_RUNTIME": "1"}) is True
    assert server_module.local_routes_enabled({}) is False
    assert server_module.local_routes_enabled({"VOICE_ACP_LOCAL_RUNTIME": "0"}) is False


def test_default_app_gates_loopback_and_admin_routes(server_module):
    """Without the opt-in, only the three stable quickstart routes are mounted."""
    gated = server_module.create_app(enable_local_routes=False)
    opted_in = server_module.create_app(enable_local_routes=True)

    assert gated.state.task_runtime is None
    assert gated.state.work_store is None
    assert opted_in.state.task_runtime is not None
    assert opted_in.state.work_store is not None

    with TestClient(gated) as client:
        # Base quickstart route stays available.
        assert client.get("/get_config").status_code == 200
        # Derivative loopback + admin surfaces are absent entirely (404, not 403).
        assert client.get("/local/workspace").status_code == 404
        assert client.get("/local/runtime").status_code == 404
        assert client.post("/local/workspace/browse").status_code == 404
        assert client.post("/validation/admin/permissions", json={}).status_code == 404

    with TestClient(opted_in) as client:
        assert client.get("/local/workspace").status_code == 200


def test_local_lifespan_recovers_work_before_acceptance(server_module):
    local_app = server_module.create_app(enable_local_routes=True)
    store = local_app.state.work_store
    receipt, _ = store.create_or_get("scope-a", "turn-a", "Run tests")
    store.transition(receipt.work_id, "starting")
    store.transition(receipt.work_id, "running")

    with TestClient(local_app):
        recovered = store.get(receipt.work_id)
        assert recovered.state == "failed"
        assert recovered.error == "Local Runner restarted before Work completed."


def test_invalid_workspace_override_does_not_crash_import(
    fake_env, monkeypatch, tmp_path
):
    """A bad VOICE_ACP_WORKSPACE must not raise during module import."""
    monkeypatch.setenv("VOICE_ACP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("VOICE_ACP_WORKSPACE", str(tmp_path / "does-not-exist"))
    sys.modules.pop("server", None)
    sys.modules.pop("agent", None)

    import server

    importlib.reload(server)

    # Import succeeded and the invalid override left the workspace unconfigured.
    assert server.workspace_service.status().state == "unconfigured"
