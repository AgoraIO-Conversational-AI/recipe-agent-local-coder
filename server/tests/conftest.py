"""Shared fixtures for the server test suite.

Standalone: no Agora cloud, no real credentials. A deterministic fake env is
injected, and python-dotenv is neutralized so a developer's local file cannot
add unrelated state during tests.
"""
import importlib
import os
import sys

import pytest

# Make `import server` / `import agent` resolve to server/src/*.
_SERVER_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _SERVER_SRC not in sys.path:
    sys.path.insert(0, _SERVER_SRC)

FAKE_ENV = {
    "AGORA_APP_ID": "0123456789abcdef0123456789abcdef",
    "AGORA_APP_CERTIFICATE": "fedcba9876543210fedcba9876543210",
    "VALIDATION_MODEL": "gpt-4o-mini",
    "PUBLIC_VALIDATION_BASE_URL": "https://validation.example.com",
}


@pytest.fixture
def anyio_backend():
    """Keep async tests on asyncio; the application does not depend on Trio."""
    return "asyncio"


@pytest.fixture
def fake_env(monkeypatch):
    """Inject a deterministic env and stop dotenv from clobbering it."""
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    for key, value in FAKE_ENV.items():
        monkeypatch.setenv(key, value)
    for key in (
        "VOICE_ACP_WORKSPACE",
        "VOICE_ACP_COMMAND_JSON",
        "CODEX_PATH",
        "CODEX_API_KEY",
        "OPENAI_API_KEY",
        "INITIAL_AGENT_MODE",
    ):
        monkeypatch.delenv(key, raising=False)
    return dict(FAKE_ENV)


class FakeAgent:
    """Stand-in for the real Agent (mirrors scripts/run_fake_server.py)."""

    def __init__(self):
        self.started = []
        self.stopped = []

    async def start(self, channel_name, agent_uid, user_uid, output_audio_codec=None):
        self.started.append((channel_name, agent_uid, user_uid, output_audio_codec))
        return {
            "agent_id": f"fake-agent-{agent_uid}",
            "channel_name": channel_name,
            "status": "started",
        }

    async def stop(self, agent_id):
        self.stopped.append(agent_id)


@pytest.fixture
def server_module(fake_env, monkeypatch, tmp_path):
    """Import server.py fresh, with the fake env + neutralized dotenv applied."""
    monkeypatch.setenv("VOICE_ACP_STATE_DIR", str(tmp_path / "voice-acp-state"))
    # Build the module-level app with the loopback derivative routes opted in,
    # matching the local Codex development runtime the routes exist for.
    monkeypatch.setenv("VOICE_ACP_LOCAL_RUNTIME", "1")
    sys.modules.pop("server", None)
    sys.modules.pop("agent", None)
    import server

    importlib.reload(server)
    # Existing route tests do not exercise the dedicated listener. Production
    # ingress composition has its own fake-listener suite.
    server.app = server.create_app(
        enable_local_routes=True,
        enable_managed_ingress=False,
    )
    return server


@pytest.fixture
def client(server_module):
    """A FastAPI TestClient whose agent is a FakeAgent (no cloud)."""
    from fastapi.testclient import TestClient

    fake = FakeAgent()
    server_module.agent = fake
    test_client = TestClient(server_module.app)
    test_client.fake_agent = fake
    return test_client
