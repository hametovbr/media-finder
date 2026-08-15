"""Generic settings, readiness, and attribution browser routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .acquisition import create_download_client_instance
from .modules.registry import FIRST_PARTY_MODULES
from .sdk.settings import describe_settings
from .ui_context import UIContext
from .ui_i18n import module_translation
from .ui_runtime import ProwlarrSettings
from .ui_security import translation


def settings_router(context: UIContext) -> APIRouter:
    router = APIRouter()

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        session, fresh = context.session_for(request)
        locale = context.locale_for(request, session)
        provider_fields = {
            key: describe_settings(provider.config_model)
            for key, provider in context.runtime.supported_providers.items()
        }
        client_fields = {
            key: describe_settings(registration.config_model)
            for key, registration in FIRST_PARTY_MODULES.download_clients.items()
        }
        clients = context.repository.clients()
        archived_clients = context.repository.clients(archived=True)
        feedback_key = None
        if request.query_params.get("saved") == "1":
            feedback_key = "Settings saved."
        elif request.query_params.get("client") == "archived":
            feedback_key = "Download client archived."
        elif request.query_params.get("client") == "restored":
            feedback_key = "Download client restored."
        response = context.render(
            "settings.html",
            locale=locale,
            session=session,
            provider_fields=provider_fields,
            client_fields=client_fields,
            clients=clients,
            archived_clients=archived_clients,
            client_readiness={
                client.id: context.runtime.client_ready(client) for client in clients
            },
            prowlarr_fields=describe_settings(ProwlarrSettings),
            prowlarr_ready=context.runtime.prowlarr_ready(),
            provider_readiness={
                key: context.runtime.provider_ready(key)
                for key in context.runtime.supported_providers
            },
            mt=lambda module_key, key: module_translation(module_key, key, locale),
            feedback=translation(locale).gettext(feedback_key) if feedback_key else None,
        )
        if fresh:
            context.set_session(response, session)
        return response

    @router.post("/ui/settings/providers/{provider_key}")
    async def save_provider_settings(request: Request, provider_key: str) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        _, form = checked
        provider = context.runtime.supported_providers.get(provider_key)
        if provider is None:
            return context.ui_error(request, "metadata_provider_not_found", 404)
        try:
            payload = {key: value for key, value in form.items() if key != "csrf"}
            normalized = provider.config_model.model_validate(payload).model_dump(mode="json")
        except Exception:
            return context.ui_error(request, "metadata_provider_configuration_invalid", 422)
        context.repository.store_setting(f"metadata_provider:{provider_key}", normalized)
        return context.redirect("/settings?saved=1")

    @router.post("/ui/settings/prowlarr")
    async def save_prowlarr_settings(request: Request) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        _, form = checked
        try:
            payload = {key: value for key, value in form.items() if key != "csrf"}
            normalized = ProwlarrSettings.model_validate(payload).model_dump(mode="json")
        except Exception:
            return context.ui_error(request, "prowlarr_configuration_invalid", 422)
        context.repository.store_setting("prowlarr", normalized)
        return context.redirect("/settings?saved=1")

    @router.post("/ui/settings/clients")
    async def save_client_settings(request: Request) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        _, form = checked
        try:
            config = {
                key: value
                for key, value in form.items()
                if key not in {"csrf", "name", "module_key"}
            }
            with context.sessions() as database:
                create_download_client_instance(
                    database,
                    name=form.get("name", ""),
                    module_key=form.get("module_key", ""),
                    config_payload=config,
                )
        except Exception:
            return context.ui_error(request, "download_client_configuration_invalid", 422)
        return context.redirect("/settings?saved=1")

    async def change_client_archive(
        request: Request, client_id: str, *, restore: bool
    ) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        if not context.repository.change_client(client_id, restore=restore):
            return context.ui_error(request, "download_client_not_found", 404)
        state = "restored" if restore else "archived"
        return context.redirect(f"/settings?client={state}")

    @router.post("/ui/settings/clients/{client_id}/archive")
    async def archive_client(request: Request, client_id: str) -> HTMLResponse:
        return await change_client_archive(request, client_id, restore=False)

    @router.post("/ui/settings/clients/{client_id}/restore")
    async def restore_client(request: Request, client_id: str) -> HTMLResponse:
        return await change_client_archive(request, client_id, restore=True)

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
