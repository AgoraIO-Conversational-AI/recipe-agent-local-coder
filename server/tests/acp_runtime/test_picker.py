"""Native picker process-boundary tests without opening system UI."""

import pytest

from acp_runtime.picker import MacOSDirectoryPicker


class FakeProcess:
    def __init__(self, *, returncode: int, stdout: bytes, stderr: bytes) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


@pytest.mark.anyio
async def test_picker_uses_osascript_without_a_shell(monkeypatch):
    observed: tuple[object, ...] | None = None

    async def fake_exec(*args, **kwargs):
        nonlocal observed
        observed = (*args, kwargs)
        return FakeProcess(returncode=0, stdout=b"/tmp/project/\n", stderr=b"")

    monkeypatch.setattr("acp_runtime.picker.sys.platform", "darwin")
    monkeypatch.setattr("acp_runtime.picker.asyncio.create_subprocess_exec", fake_exec)

    selected = await MacOSDirectoryPicker().pick()

    assert selected == "/tmp/project/"
    assert observed is not None
    assert observed[0] == "/usr/bin/osascript"
    assert "shell" not in observed[-1]


@pytest.mark.anyio
async def test_picker_returns_none_for_standard_macos_cancellation(monkeypatch):
    async def fake_exec(*_args, **_kwargs):
        return FakeProcess(
            returncode=1,
            stdout=b"",
            stderr=b"execution error: User canceled. (-128)\n",
        )

    monkeypatch.setattr("acp_runtime.picker.sys.platform", "darwin")
    monkeypatch.setattr("acp_runtime.picker.asyncio.create_subprocess_exec", fake_exec)

    assert await MacOSDirectoryPicker().pick() is None


@pytest.mark.anyio
async def test_picker_rejects_non_macos_without_starting_a_process(monkeypatch):
    async def fail_if_started(*_args, **_kwargs):
        raise AssertionError("picker process must not start outside macOS")

    monkeypatch.setattr("acp_runtime.picker.sys.platform", "linux")
    monkeypatch.setattr(
        "acp_runtime.picker.asyncio.create_subprocess_exec", fail_if_started
    )

    with pytest.raises(RuntimeError, match="requires macOS"):
        await MacOSDirectoryPicker().pick()
