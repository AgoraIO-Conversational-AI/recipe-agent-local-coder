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
    return _OPENAI_STYLE.sub("[REDACTED]", redacted)
