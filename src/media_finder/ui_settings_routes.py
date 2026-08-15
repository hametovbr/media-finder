"""Read-only environment diagnostics and attribution browser routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .models import DownloadClientInstance
from .modules.registry import FIRST_PARTY_MODULES
from .sdk.types import EnvironmentVariableSpec
from .system_clients import SYSTEM_QBITTORRENT_ID
from .ui_context import UIContext
from .ui_i18n import module_translation
from .ui_runtime import PROWLARR_INTEGRATION, RuntimeResult
from .ui_security import translation


def settings_router(context: UIContext) -> APIRouter:
    router = APIRouter()

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        session, fresh = context.session_for(request)
        locale = context.locale_for(request, session)
        translator = translation(locale).gettext

        def diagnostic(
            key: str,
            declarations: tuple[EnvironmentVariableSpec, ...],
            result: RuntimeResult[Any],
        ) -> dict[str, Any]:
            variables = [
                {
                    "name": declaration.name,
                    "required": declaration.required,
                    "secret": declaration.secret,
                    "state": (
                        "set" if context.runtime.environment_is_set(declaration.name) else "missing"
                    ),
                    "description": _environment_description(
                        key, declaration.description_key, locale, translator
                    ),
                }
                for declaration in declarations
            ]
            missing = any(
                variable["required"] and variable["state"] == "missing" for variable in variables
            )
            state = (
                "missing" if missing else ("ready" if result.value is not None else "unavailable")
            )
            return {"key": key, "state": state, "variables": variables}

        tmdb = FIRST_PARTY_MODULES.metadata_providers["tmdb"]
        qbittorrent = FIRST_PARTY_MODULES.download_clients["qbittorrent"]
        with context.sessions() as database:
            system_client = database.get(DownloadClientInstance, SYSTEM_QBITTORRENT_ID)
        assert system_client is not None
        diagnostics = [
            diagnostic("tmdb", tmdb.environment, context.runtime.metadata_provider("tmdb")),
            diagnostic("prowlarr", PROWLARR_INTEGRATION.environment, context.runtime.prowlarr()),
            diagnostic(
                "qbittorrent",
                qbittorrent.environment,
                context.runtime.download_client(system_client),
            ),
        ]
        response = context.render(
            "settings.html",
            locale=locale,
            session=session,
            diagnostics=diagnostics,
            mt=lambda module_key, key: module_translation(module_key, key, locale),
        )
        if fresh:
            context.set_session(response, session)
        return response

    @router.get("/about", response_class=HTMLResponse)
    async def about_page(request: Request) -> HTMLResponse:
        session, fresh = context.session_for(request)
        locale = context.locale_for(request, session)
        attributions = [factory() for factory in FIRST_PARTY_MODULES.static_attributions]
        attributions.extend(context.runtime.configured_provider_attributions())
        response = context.render(
            "about.html",
            locale=locale,
            session=session,
            attributions=attributions,
        )
        if fresh:
            context.set_session(response, session)
        return response

    return router


def _environment_description(
    integration: str,
    description_key: str,
    locale: str,
    gettext: Callable[[str], str],
) -> str:
    if integration in FIRST_PARTY_MODULES.metadata_providers or integration in (
        FIRST_PARTY_MODULES.download_clients
    ):
        return module_translation(integration, description_key, locale)
    core_descriptions = {
        "integration.prowlarr.environment.url": "Prowlarr base URL",
        "integration.prowlarr.environment.api_key": "Prowlarr API key",
    }
    return gettext(core_descriptions[description_key])
