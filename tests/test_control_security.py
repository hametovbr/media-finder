import asyncio
import hmac
from unittest.mock import patch

from media_finder_control import Locale

from media_finder.control_security import BackendBrowserSecurity
from media_finder.ui_security import SessionSigner


def test_browser_security_reads_and_writes_compatible_session_payload() -> None:
    secret = b"browser-session-secret-at-least-32-bytes"
    legacy = SessionSigner(secret).dumps(
        {"csrf": "existing", "locale": "ru", "metadata_locale": "en"}
    )
    security = BackendBrowserSecurity(secret=secret)

    async def scenario() -> None:
        session = await security.load_session(cookie=legacy, accept_language="en-US")
        assert session.ui_locale is Locale.RU
        assert session.metadata_locale is Locale.EN
        assert session.metadata_locale_explicit is True
        encoded = await security.serialize_session(session=session)
        assert SessionSigner(secret).loads(encoded) == {
            "csrf": "existing",
            "locale": "ru",
            "metadata_locale": "en",
        }

    asyncio.run(scenario())


def test_browser_security_inherits_locale_and_recovers_invalid_session() -> None:
    security = BackendBrowserSecurity(secret=b"browser-session-secret-at-least-32-bytes")

    async def scenario() -> None:
        session = await security.load_session(cookie="invalid", accept_language="ru-RU, en;q=0.8")
        assert session.ui_locale is Locale.RU
        assert session.metadata_locale is Locale.RU
        assert session.metadata_locale_explicit is False
        assert len(session.csrf_token) >= 32

    asyncio.run(scenario())


def test_csrf_comparison_is_constant_time_and_reusable() -> None:
    security = BackendBrowserSecurity(secret=b"browser-session-secret-at-least-32-bytes")

    async def scenario() -> None:
        session = await security.load_session(cookie=None, accept_language="en")
        with patch(
            "media_finder.control_security.hmac.compare_digest", wraps=hmac.compare_digest
        ) as compared:
            assert await security.validate_csrf(session=session, token=session.csrf_token)
            assert await security.validate_csrf(session=session, token=session.csrf_token)
            assert not await security.validate_csrf(session=session, token="wrong")
        assert compared.call_count == 3

    asyncio.run(scenario())
