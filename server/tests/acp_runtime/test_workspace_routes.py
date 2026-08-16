"""Loopback Project Folder API tests with a fake native picker."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from acp_runtime.acp_client import AcpSession
from acp_runtime.readiness import LocalRuntimeCoordinator
from acp_runtime.routes import build_runtime_router, build_workspace_router
from acp_runtime.workspace import WorkspaceConfigStore, WorkspaceService


class FakeDirectoryPicker:
    def __init__(self) -> None:
        self.result: str | None = None
        self.calls = 0

    async def pick(self) -> str | None:
        self.calls += 1
        return self.result


class FakeAcpClient:
    def __init__(self) -> None:
        self.opened: list[str] = []
        self.close_calls = 0
        self.open_error: Exception | None = None

    async def open(self, primary_directory: str) -> AcpSession:
        self.opened.append(primary_directory)
        if self.open_error is not None:
            raise self.open_error
        return AcpSession(primary_directory=primary_directory)

    async def close(self) -> None:
        self.close_calls += 1


def make_app(tmp_path):
    service = WorkspaceService(WorkspaceConfigStore(tmp_path / "workspace.json"))
    picker = FakeDirectoryPicker()
    fake_acp = FakeAcpClient()
    runtime = LocalRuntimeCoordinator(service, fake_acp)
    app = FastAPI()
    app.include_router(build_workspace_router(service=service, picker=picker, runtime=runtime))
    app.include_router(build_runtime_router(runtime=runtime))
    return app, picker, runtime, fake_acp


def test_get_workspace_returns_unconfigured_envelope(tmp_path):
    app, _picker, _runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/local/workspace")

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "msg": "success",
        "data": {
            "state": "unconfigured",
            "profile": {
                "id": "codex",
                "label": "Codex",
                "requires_primary_directory": True,
                "supports_additional_directories": False,
            },
            "workspace": None,
        },
    }


def test_workspace_routes_are_loopback_only(tmp_path):
    app, _picker, _runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app, client=("203.0.113.10", 50000)) as remote:
        assert remote.get("/local/workspace").status_code == 403
        assert remote.get("/local/runtime").status_code == 403
        assert remote.post("/local/workspace/browse").status_code == 403
        assert (
            remote.put("/local/workspace", json={"path": "/tmp"}).status_code
            == 403
        )
        assert remote.delete("/local/workspace").status_code == 403


def test_browse_persists_only_picker_result(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    app, picker, runtime, _fake_acp = make_app(tmp_path)
    picker.result = str(project)

    with TestClient(app) as client:
        response = client.post("/local/workspace/browse")
        restored = client.get("/local/workspace")

    assert response.status_code == 200
    assert response.json()["data"]["workspace"]["primary_directory"] == str(
        project.resolve()
    )
    assert restored.json()["data"] == response.json()["data"]
    assert picker.calls == 1
    assert runtime.status().state == "ready"


def test_cancelled_picker_does_not_replace_selection(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    app, picker, _runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        selected = client.put("/local/workspace", json={"path": str(project)})
        picker.result = None
        cancelled = client.post("/local/workspace/browse")
        restored = client.get("/local/workspace")

    assert selected.status_code == 200
    assert cancelled.status_code == 409
    assert cancelled.json()["detail"] == "Project Folder selection was cancelled"
    assert restored.json()["data"] == selected.json()["data"]


def test_manual_selection_rejects_invalid_folder_without_replacing_state(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    app, _picker, _runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        client.put("/local/workspace", json={"path": str(project)})
        rejected = client.put(
            "/local/workspace", json={"path": str(tmp_path / "missing")}
        )
        restored = client.get("/local/workspace")

    assert rejected.status_code == 400
    assert restored.json()["data"]["workspace"]["primary_directory"] == str(
        project.resolve()
    )


def test_delete_clears_selection_without_touching_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    app, _picker, _runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        client.put("/local/workspace", json={"path": str(project)})
        cleared = client.delete("/local/workspace")

    assert cleared.status_code == 200
    assert cleared.json()["data"]["state"] == "unconfigured"
    assert project.is_dir()


def test_get_runtime_reports_configuration_required_without_starting_acp(tmp_path):
    app, _picker, runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/local/runtime")

    assert response.status_code == 200
    assert response.json()["data"]["state"] == "configuration_required"
    assert runtime.status().state == "configuration_required"


def test_failed_activation_keeps_the_previous_workspace_selection(tmp_path):
    previous = tmp_path / "previous"
    next_project = tmp_path / "next"
    previous.mkdir()
    next_project.mkdir()
    app, _picker, runtime, fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        selected = client.put("/local/workspace", json={"path": str(previous)})
        fake_acp.open_error = RuntimeError("missing executable")
        failed = client.put("/local/workspace", json={"path": str(next_project)})
        restored = client.get("/local/workspace")

    assert selected.status_code == 200
    assert failed.status_code == 503
    assert failed.json()["detail"] == "Could not start the local Codex runtime: missing executable"
    assert restored.json()["data"]["workspace"]["primary_directory"] == str(previous)
