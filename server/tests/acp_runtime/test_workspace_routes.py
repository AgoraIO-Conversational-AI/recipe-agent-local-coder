"""Loopback Project Folder API tests with a fake native picker."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from acp_runtime.routes import build_workspace_router
from acp_runtime.workspace import WorkspaceConfigStore, WorkspaceService


class FakeDirectoryPicker:
    def __init__(self) -> None:
        self.result: str | None = None
        self.calls = 0

    async def pick(self) -> str | None:
        self.calls += 1
        return self.result


def make_app(tmp_path):
    service = WorkspaceService(WorkspaceConfigStore(tmp_path / "workspace.json"))
    picker = FakeDirectoryPicker()
    app = FastAPI()
    app.include_router(build_workspace_router(service=service, picker=picker))
    return app, picker


def test_get_workspace_returns_unconfigured_envelope(tmp_path):
    app, _picker = make_app(tmp_path)

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
    app, _picker = make_app(tmp_path)

    with TestClient(app, client=("203.0.113.10", 50000)) as remote:
        assert remote.get("/local/workspace").status_code == 403
        assert remote.post("/local/workspace/browse").status_code == 403
        assert (
            remote.put("/local/workspace", json={"path": "/tmp"}).status_code
            == 403
        )
        assert remote.delete("/local/workspace").status_code == 403


def test_browse_persists_only_picker_result(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    app, picker = make_app(tmp_path)
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


def test_cancelled_picker_does_not_replace_selection(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    app, picker = make_app(tmp_path)

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
    app, _picker = make_app(tmp_path)

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
    app, _picker = make_app(tmp_path)

    with TestClient(app) as client:
        client.put("/local/workspace", json={"path": str(project)})
        cleared = client.delete("/local/workspace")

    assert cleared.status_code == 200
    assert cleared.json()["data"]["state"] == "unconfigured"
    assert project.is_dir()
