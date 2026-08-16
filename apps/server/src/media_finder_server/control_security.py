"""Backend-owned signed browser-session and CSRF implementation."""

import base64
import hashlib
import hmac
import json
import secrets

from media_finder_control import BrowserSession, Locale

SUPPORTED_LOCALES = frozenset(Locale)


def _resolve_locale(override: str | None, accept_language: str | None) -> Locale:
    if override is not None:
        try:
            return Locale(override)
        except ValueError:
            pass
    for choice in (accept_language or "").split(","):
        language = choice.split(";", 1)[0].strip().split("-", 1)[0].casefold()
        try:
            return Locale(language)
        except ValueError:
            continue
    return Locale.EN


class BackendBrowserSecurity:
    """Preserve the existing signed cookie format behind a public port."""

    def __init__(self, *, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("session_secret_too_short")
        self._secret = secret

    async def load_session(
        self, *, cookie: str | None, accept_language: str | None
    ) -> BrowserSession:
        values = self._loads(cookie) if cookie else None
        values = values or {}
        ui_locale = _resolve_locale(values.get("locale"), accept_language)
        explicit = values.get("metadata_locale") in {value.value for value in Locale}
        metadata_locale = Locale(values["metadata_locale"]) if explicit else ui_locale
        return BrowserSession(
            ui_locale=ui_locale,
            metadata_locale=metadata_locale,
            metadata_locale_explicit=explicit,
            csrf_token=values.get("csrf") or secrets.token_urlsafe(32),
            is_new=not bool(values),
        )

    async def serialize_session(self, *, session: BrowserSession) -> str:
        values = {
            "csrf": session.csrf_token,
            "locale": session.ui_locale.value,
        }
        if session.metadata_locale_explicit:
            values["metadata_locale"] = session.metadata_locale.value
        payload = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
        signature = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"

    async def validate_csrf(self, *, session: BrowserSession, token: str | None) -> bool:
        return hmac.compare_digest(token or "", session.csrf_token)

    def _loads(self, token: str) -> dict[str, str] | None:
        try:
            encoded, supplied = token.rsplit(".", 1)
            expected = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(supplied, expected):
                return None
            padding = "=" * (-len(encoded) % 4)
            raw = json.loads(base64.urlsafe_b64decode(encoded + padding))
            if not isinstance(raw, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in raw.items()
            ):
                return None
            return raw
        except Exception:
            return None
