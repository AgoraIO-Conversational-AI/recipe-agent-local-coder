"""Socket-peer checks shared by local control routes."""

from fastapi import HTTPException, Request


def require_loopback(request: Request) -> None:
    """Reject callers whose actual socket peer is not loopback."""
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=403, detail="loopback access required")
