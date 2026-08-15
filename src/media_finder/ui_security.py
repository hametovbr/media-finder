"""Locale, signed-session, and form-decoding boundaries for the browser UI."""

from __future__ import annotations

import base64
import gettext
import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Request

SUPPORTED_LOCALES = frozenset({"en", "ru"})
SESSION_COOKIE = "mf_session"
LOCALE_ROOT = Path(__file__).with_name("locales")
ERROR_MESSAGES = {
    "release_search_token_expired": "The release selection expired. Search again.",
}


class SessionSigner:
    """Authenticate compact browser-session values without server-side user state."""

    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("session_secret_too_short")
        self._secret = secret

    def dumps(self, value: dict[str, str]) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
        signature = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"

    def loads(self, token: str) -> dict[str, str]:
        try:
            encoded, supplied = token.rsplit(".", 1)
            expected = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(supplied, expected):
                raise ValueError
            padding = "=" * (-len(encoded) % 4)
            raw = json.loads(base64.urlsafe_b64decode(encoded + padding))
            if not isinstance(raw, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in raw.items()
            ):
                raise ValueError
            return raw
        except Exception:
            raise ValueError("invalid_session") from None


def resolve_locale(override: str | None, accept_language: str | None) -> str:
    if override in SUPPORTED_LOCALES:
        return override
    for choice in (accept_language or "").split(","):
        language = choice.split(";", 1)[0].strip().split("-", 1)[0].casefold()
        if language in SUPPORTED_LOCALES:
            return language
    return "en"


def translation(locale: str) -> gettext.NullTranslations:
    return gettext.translation("messages", LOCALE_ROOT, languages=[locale], fallback=True)


def error_message(code: str, locale: str) -> tuple[str, str]:
    source = ERROR_MESSAGES.get(code, "A safely hidden error occurred.")
    return translation(resolve_locale(locale, None)).gettext(source), code


async def decode_form(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("application/x-www-form-urlencoded"):
        return {}
    values = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    return {key: items[-1] for key, items in values.items() if items}
