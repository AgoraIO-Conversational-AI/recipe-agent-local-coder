"""Durable selection of one ACP Workspace Scope."""

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class AgentProfile:
    """Capabilities that shape Workspace Settings without naming a UI vendor."""

    id: str = "codex"
    label: str = "Codex"
    requires_primary_directory: bool = True
    supports_additional_directories: bool = False


CODEX_PROFILE = AgentProfile()


@dataclass(frozen=True)
class WorkspaceScope:
    """ACP session context for one resolved Project Folder."""

    id: str
    label: str
    primary_directory: str


@dataclass(frozen=True)
class WorkspaceStatus:
    state: Literal["unconfigured", "ready", "invalid"]
    profile: AgentProfile
    workspace: WorkspaceScope | None


class WorkspaceConfigStore:
    """Persist exactly one Workspace Scope as an atomic local JSON record."""

    SCHEMA_VERSION = "1.0"

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def default(cls) -> "WorkspaceConfigStore":
        state_directory = os.getenv("VOICE_ACP_STATE_DIR")
        root = (
            Path(state_directory).expanduser()
            if state_directory
            else Path.home()
            / "Library"
            / "Application Support"
            / "Agora Voice ACP"
        )
        return cls(root / "workspace.json")

    def load(self) -> WorkspaceScope | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("Unsupported Workspace configuration version")
        return WorkspaceScope(
            id=str(payload["id"]),
            label=str(payload["label"]),
            primary_directory=str(payload["primary_directory"]),
        )

    def save(self, workspace: WorkspaceScope) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            **asdict(workspace),
        }
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class WorkspaceService:
    """Validate and report the selected Workspace Scope."""

    def __init__(self, store: WorkspaceConfigStore) -> None:
        self.store = store

    def status(self) -> WorkspaceStatus:
        workspace = self.store.load()
        if workspace is None:
            return WorkspaceStatus(
                state="unconfigured",
                profile=CODEX_PROFILE,
                workspace=None,
            )
        path = Path(workspace.primary_directory)
        state = "ready" if path.is_absolute() and path.is_dir() else "invalid"
        return WorkspaceStatus(
            state=state,
            profile=CODEX_PROFILE,
            workspace=workspace,
        )

    def select(self, path: str) -> WorkspaceStatus:
        try:
            resolved = Path(path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("Project Folder must be an existing directory") from exc
        if not resolved.is_dir():
            raise ValueError("Project Folder must be an existing directory")

        workspace = WorkspaceScope(
            id=hashlib.sha256(os.fsencode(resolved)).hexdigest()[:24],
            label=resolved.name or str(resolved),
            primary_directory=str(resolved),
        )
        self.store.save(workspace)
        return WorkspaceStatus(
            state="ready",
            profile=CODEX_PROFILE,
            workspace=workspace,
        )

    def clear(self) -> WorkspaceStatus:
        self.store.clear()
        return WorkspaceStatus(
            state="unconfigured",
            profile=CODEX_PROFILE,
            workspace=None,
        )
