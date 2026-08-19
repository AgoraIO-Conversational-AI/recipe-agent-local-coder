"""Public types for one Managed Voice LLM MCP credential."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CapabilityLease:
    """A pending per-Agent credential, retained only until activation/revocation."""

    lease_id: str
    bearer: str = field(repr=False)
    workspace_id: str = ""
    workspace_generation: int = 0
    issued_at: float = 0.0


@dataclass(frozen=True)
class CapabilityBinding:
    """The safe identity resolved from one active bearer."""

    credential_id: str
    workspace_id: str
    workspace_generation: int
    agora_agent_id: str
    issued_at: float
