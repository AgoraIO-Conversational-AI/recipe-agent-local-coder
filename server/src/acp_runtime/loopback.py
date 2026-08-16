"""Socket-peer and browser-origin checks shared by local control routes."""

from urllib.parse import urlsplit

from fastapi import HTTPException, Request

# Loopback socket peers accepted by the network-layer check. "testclient" is the
# FastAPI TestClient's synthetic peer.
_LOOPBACK_PEERS = {"127.0.0.1", "::1", "testclient"}
# Loopback host names accepted in the Origin/Host headers. "testserver" is the
# FastAPI TestClient's default Host.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver"}
_FORBIDDEN = HTTPException(status_code=403, detail="loopback access required")


def _hostname(netloc: str) -> str:
    """Return the lowercased host without its port, unwrapping IPv6 brackets."""
    host = netloc.strip().lower()
    if host.startswith("["):  # IPv6 literal, e.g. [::1]:8000
        return host[1 : host.index("]")] if "]" in host else host[1:]
    return host.rsplit(":", 1)[0] if ":" in host else host


def require_loopback(request: Request) -> None:
    """Reject non-loopback socket peers and cross-site browser callers.

    The socket-peer check blocks other machines. The Origin/Host checks block a
    local browser used as a confused deputy by a malicious web page: browser
    traffic always has a loopback peer, but the forbidden Origin header (which
    page JavaScript cannot forge) reveals a cross-site caller, and the Host check
    closes the DNS-rebinding gap for requests that carry no Origin. Non-browser
    callers (curl, native, and the Next server-side rewrite) send no Origin and
    are unaffected.
    """
    peer = request.client.host if request.client else ""
    if peer not in _LOOPBACK_PEERS:
        raise _FORBIDDEN

    origin = request.headers.get("origin")
    if origin is not None and _hostname(urlsplit(origin).netloc) not in _LOOPBACK_HOSTS:
        raise _FORBIDDEN

    host_header = request.headers.get("host")
    if host_header is not None and _hostname(host_header) not in _LOOPBACK_HOSTS:
        raise _FORBIDDEN
