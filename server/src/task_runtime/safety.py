"""Conservative redaction for user- and ACP-authored durable text."""

import re


_NAMED_SECRET = re.compile(
    r"(?i)\b(?P<key>[A-Z0-9_-]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|"
    r"CERTIFICATE|AUTHORIZATION|COOKIE)[A-Z0-9_-]*)\b"
    r"(?P<separator>\s*[=:]\s*)"
    r"(?P<value>Bearer\s+[^\s,;]+|\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_OPENAI_STYLE = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
_PROVIDER_TOKEN = re.compile(
    r"\b(?:"
    r"github_pat_[A-Za-z0-9_]{12,}|"
    r"gh[pousr]_[A-Za-z0-9]{12,}|"
    r"(?:AKIA|ASIA)[A-Z0-9]{16}|"
    r"AIza[A-Za-z0-9_-]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r")\b"
)
_ENV_ASSIGNMENT = re.compile(
    r"(?m)\b(?P<key>[A-Z][A-Z0-9_]{1,63})(?P<separator>\s*=\s*)"
    r"(?P<value>[^\s,;]+)"
)
_URL_CREDENTIALS = re.compile(
    r"(?i)(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<credentials>[^/@\s]+@)"
)
_PEM_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]*(?:PRIVATE KEY|CERTIFICATE)-----.*?"
    r"-----END [A-Z0-9 ]*(?:PRIVATE KEY|CERTIFICATE)-----",
    re.DOTALL,
)
_QUOTED_SECRET = re.compile(
    r"(?i)(?P<prefix>[\"'](?:[^\"']*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|"
    r"PASSWD|CERTIFICATE|AUTHORIZATION|COOKIE)[^\"']*)[\"']\s*:\s*)"
    r"(?P<quote>[\"'])[^\"']*(?P=quote)"
)


def redact_durable_text(value: str) -> str:
    """Remove recognizable credentials before text crosses the SQLite boundary."""

    def replace_named(match: re.Match[str]) -> str:
        return f"{match.group('key')}{match.group('separator')}[REDACTED]"

    redacted = _QUOTED_SECRET.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('quote')}"
            f"[REDACTED]{match.group('quote')}"
        ),
        value,
    )
    redacted = _NAMED_SECRET.sub(replace_named, redacted)
    redacted = _BEARER.sub("Bearer [REDACTED]", redacted)
    redacted = _OPENAI_STYLE.sub("[REDACTED]", redacted)
    redacted = _PROVIDER_TOKEN.sub("[REDACTED]", redacted)
    redacted = _ENV_ASSIGNMENT.sub(
        lambda match: (
            f"{match.group('key')}{match.group('separator')}[REDACTED]"
        ),
        redacted,
    )
    redacted = _URL_CREDENTIALS.sub(
        lambda match: f"{match.group('scheme')}[REDACTED]@",
        redacted,
    )
    return _PEM_BLOCK.sub("[REDACTED PEM]", redacted)
