"""Ordinary FastAPI startup must not launch the optional ACP runtime."""

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
