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

from .ui_i18n import message_for

SUPPORTED_LOCALES = frozenset({"en", "ru"})
SESSION_COOKIE = "mf_session"
LOCALE_ROOT = Path(__file__).with_name("locales")
MAX_UI_FORM_BYTES = 1024 * 1024


class FormBodyTooLarge(ValueError):
    def __init__(self) -> None:
        super().__init__("ui_form_too_large")


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
    return message_for(code, resolve_locale(locale, None)), code


async def decode_form(request: Request) -> dict[str, str]:
    cached = getattr(request.state, "media_finder_decoded_form", None)
    if isinstance(cached, dict):
        return dict(cached)
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("application/x-www-form-urlencoded"):
        return {}
    declared = request.headers.get("content-length")
    try:
        if declared is not None and int(declared) > MAX_UI_FORM_BYTES:
            raise FormBodyTooLarge
    except ValueError:
        raise FormBodyTooLarge from None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_UI_FORM_BYTES:
            raise FormBodyTooLarge
        chunks.append(chunk)
    try:
        encoded = b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError:
        return {}
    values = parse_qs(encoded, keep_blank_values=True)
    decoded = {key: items[-1] for key, items in values.items() if items}
    request.state.media_finder_decoded_form = decoded
    return dict(decoded)
