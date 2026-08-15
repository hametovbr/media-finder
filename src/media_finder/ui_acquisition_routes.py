"""Prowlarr search, live destination, acquisition, and reconcile browser routes."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from .acquisition import AcquisitionRequest, AcquisitionService, DestinationUnavailable
from .models import DownloadClientInstance, MediaItem
from .ui_context import UIContext
from .ui_i18n import code_for_exception
from .ui_security import translation


def acquisition_router(context: UIContext) -> APIRouter:
    router = APIRouter()

    @router.post("/ui/items/{item_id}/releases/search", response_class=HTMLResponse)
    async def release_search(request: Request, item_id: str) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        session, form = checked
        prowlarr_result = context.runtime.prowlarr()
        if prowlarr_result.value is None:
            return context.ui_error(request, "prowlarr_not_configured", 422)
        filters = {"indexerIds": form["indexer"]} if form.get("indexer") else {}
        try:
            results = prowlarr_result.value.search(form.get("query", ""), filters)
        except Exception as error:
            return context.ui_error(
                request, code_for_exception(error, "prowlarr_search_failed"), 422
            )
        body = context.templates.get_template("fragments/release_results.html").render(
            results=results,
            item_id=item_id,
            csrf=session["csrf"],
            _=translation(context.locale_for(request, session)).gettext,
        )
        return HTMLResponse(body, headers={"Vary": "HX-Request"})

    @router.get("/items/{item_id}/releases", response_class=HTMLResponse)
    async def release_page(request: Request, item_id: str) -> HTMLResponse:
        session, fresh = context.session_for(request)
        locale = context.locale_for(request, session)
        with context.sessions() as database:
            item = database.get(MediaItem, item_id)
            clients = list(
                database.scalars(
                    select(DownloadClientInstance).where(
                        DownloadClientInstance.archived_at.is_(None)
                    )
                )
            )
        if item is None:
            return context.ui_error(request, "media_item_not_found", 404)
        response = context.render(
            "release.html",
            locale=locale,
            session=session,
            item_id=item_id,
            clients=clients,
            idempotency_key=secrets.token_urlsafe(24),
        )
        if fresh:
            context.set_session(response, session)
        return response

    def destinations_response(
        destinations: object,
        *,
        locale: str,
        error_code: str | None = None,
        status_code: int = 200,
    ) -> HTMLResponse:
        body = context.templates.get_template("fragments/destinations.html").render(
            destinations=destinations,
            error_code=error_code,
            _=translation(locale).gettext,
        )
        return HTMLResponse(body, status_code=status_code, headers={"Vary": "HX-Request"})

    async def load_destinations(request: Request, client_id: str) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        session, _ = checked
        locale = context.locale_for(request, session)
        with context.sessions() as database:
            instance = database.get(DownloadClientInstance, client_id)
            if instance is None:
                return context.ui_error(request, "download_client_not_found", 404)
            try:
                destinations = context.resolved_client(instance).list_destinations()
            except Exception as error:
                return destinations_response(
                    [],
                    locale=locale,
                    error_code=code_for_exception(
                        error, "download_client_destinations_unavailable"
                    ),
                    status_code=422,
                )
        return destinations_response(destinations, locale=locale)

    @router.post("/ui/clients/destinations", response_class=HTMLResponse)
    async def selected_client_destinations(request: Request) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        _, form = checked
        return await load_destinations(request, form.get("client_instance_id", ""))

    @router.post("/ui/clients/{client_id}/destinations", response_class=HTMLResponse)
    async def client_destinations(request: Request, client_id: str) -> HTMLResponse:
        return await load_destinations(request, client_id)

    @router.post("/ui/items/{item_id}/acquisitions")
    async def submit_acquisition(request: Request, item_id: str) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        session, form = checked
        prowlarr_result = context.runtime.prowlarr()
        if prowlarr_result.value is None:
            return context.ui_error(request, "acquisition_unavailable", 422)
        with context.sessions() as database:
            item = database.get(MediaItem, item_id)
            if item is None or item.current_revision_id is None:
                return context.ui_error(request, "media_item_not_found", 404)
            service = AcquisitionService(database, prowlarr_result.value, context.resolved_client)
            try:
                acquisition = service.submit(
                    AcquisitionRequest(
                        media_item_id=item.id,
                        metadata_revision_id=item.current_revision_id,
                        client_instance_id=form.get("client_instance_id", ""),
                        destination=form.get("destination", ""),
                        release_token=form.get("release_token", ""),
                        idempotency_key=form.get("idempotency_key", ""),
                    )
                )
            except DestinationUnavailable as error:
                return destinations_response(
                    error.current_destinations,
                    locale=context.locale_for(request, session),
                    error_code="download_destination_unavailable",
                    status_code=409,
                )
            except Exception as error:
                return context.ui_error(
                    request,
                    code_for_exception(error, "acquisition_unavailable"),
                    422,
                )
        return context.redirect(f"/items/{item_id}?acquisition={acquisition.status}")

    @router.post("/ui/acquisitions/{acquisition_id}/reconcile")
    async def reconcile_acquisition(request: Request, acquisition_id: str) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        prowlarr_result = context.runtime.prowlarr()
        if prowlarr_result.value is None:
            return context.ui_error(request, "acquisition_unavailable", 422)
        try:
            with context.sessions() as database:
                acquisition = AcquisitionService(
                    database, prowlarr_result.value, context.resolved_client
                ).reconcile(acquisition_id)
        except Exception as error:
            code = code_for_exception(error, "acquisition_unavailable")
            return context.ui_error(request, code, 404 if code == "acquisition_not_found" else 422)
        return context.redirect(
            f"/items/{acquisition.media_item_id}?reconciled={acquisition.status}"
        )

    return router
