"""Public safe diagnostic redaction helpers for statically packaged modules."""

import re
from urllib.parse import urlsplit, urlunsplit

URL_PATTERN = re.compile(r"https?://[^\s\"']+")


def safe_url_origin(value: str) -> str | None:
    match = URL_PATTERN.search(value)
    if match is None:
        return None
    try:
        parsed = urlsplit(match.group(0))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        parsed_port = parsed.port
    except (UnicodeError, ValueError):
        return None
    port = f":{parsed_port}" if parsed_port is not None else ""
    return urlunsplit((parsed.scheme, parsed.hostname + port, "", "", ""))


def redact_urls(value: str, replacement: str = "[REDACTED_URL]") -> str:
    """Remove complete URLs, including credential-bearing paths and queries."""

    return URL_PATTERN.sub(replacement, value)
