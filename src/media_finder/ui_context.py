"""Shared request boundary used by the server-rendered UI route families."""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass, field
from typing import Any, cast

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment
from sqlalchemy.orm import Session, sessionmaker

from .ephemeral import EphemeralCache
from .models import DownloadClientInstance
from .sdk.protocols import DownloadClient
from .ui_i18n import acquisition_status_label, media_kind_label, message_for
from .ui_repository import UIRepository
from .ui_runtime import RuntimeResolver
from .ui_security import (
    SESSION_COOKIE,
    SessionSigner,
    decode_form,
    resolve_locale,
    translation,
)


@dataclass(slots=True)
class UIContext:
    sessions: sessionmaker[Session]
    repository: UIRepository
    runtime: RuntimeResolver
    templates: Environment
    signer: SessionSigner
    secure_cookie: bool
    metadata_selections: EphemeralCache[Any] = field(default_factory=EphemeralCache)
    manual_drafts: EphemeralCache[dict[str, object]] = field(default_factory=EphemeralCache)

    def session_for(self, request: Request) -> tuple[dict[str, str], bool]:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            try:
                return self.signer.loads(token), False
            except ValueError:
                pass
        return {"csrf": secrets.token_urlsafe(32)}, True

    def set_session(self, response: HTMLResponse, session: dict[str, str]) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            self.signer.dumps(session),
            httponly=True,
            samesite="lax",
            secure=self.secure_cookie,
            path="/",
        )

    def locale_for(self, request: Request, session: dict[str, str]) -> str:
        return resolve_locale(session.get("locale"), request.headers.get("accept-language"))

    def metadata_locale_for(self, request: Request, session: dict[str, str]) -> str:
        """Resolve the independent metadata locale, initially inheriting the UI locale."""

        return resolve_locale(session.get("metadata_locale"), self.locale_for(request, session))

    def render(
        self,
        name: str,
        *,
        locale: str,
        session: dict[str, str],
        status_code: int = 200,
        **context: Any,
    ) -> HTMLResponse:
        body = self.templates.get_template(name).render(
            locale=locale,
            metadata_locale=self.metadata_locale_for_from_session(session, locale),
            csrf=session["csrf"],
            collections=self.repository.active_collections(),
            archived_collections=self.repository.archived_collections(),
            _=translation(locale).gettext,
            error_label=lambda code: message_for(code, locale),
            kind_label=lambda kind: media_kind_label(kind, locale),
            status_label=lambda status: acquisition_status_label(status, locale),
            **context,
        )
        return HTMLResponse(body, status_code=status_code)

    @staticmethod
    def metadata_locale_for_from_session(session: dict[str, str], ui_locale: str) -> str:
        return resolve_locale(session.get("metadata_locale"), ui_locale)

    async def checked_form(self, request: Request) -> tuple[dict[str, str], dict[str, str]] | None:
        session, fresh = self.session_for(request)
        form = await decode_form(request)
        if fresh or not hmac.compare_digest(form.get("csrf", ""), session["csrf"]):
            return None
        return session, form

    def ui_error(self, request: Request, code: str, status_code: int) -> HTMLResponse:
        session, _ = self.session_for(request)
        locale = self.locale_for(request, session)
        body = self.templates.from_string(
            '<p role="alert" aria-live="assertive" data-error-code="{{ code }}">'
            "{{ message }} <code>{{ code }}</code></p>"
        ).render(code=code, message=message_for(code, locale))
        return HTMLResponse(body, status_code=status_code)

    def denied(self, request: Request) -> HTMLResponse:
        return self.ui_error(request, "csrf_invalid", 403)

    @staticmethod
    def redirect(location: str = "/") -> HTMLResponse:
        return cast(HTMLResponse, RedirectResponse(location, status_code=303))

    def resolved_client(self, instance: DownloadClientInstance) -> DownloadClient:
        if instance.archived_at is not None:
            raise ValueError("download_client_archived")
        result = self.runtime.download_client(instance)
        if result.value is None:
            raise ValueError(result.error_code or "download_client_unavailable")
        return result.value
