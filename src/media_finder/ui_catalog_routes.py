"""Catalog, collection, item-detail, and locale browser routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .ui_context import UIContext
from .ui_i18n import acquisition_status_label, message_for
from .ui_security import resolve_locale, translation


def catalog_router(context: UIContext) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        session, fresh = context.session_for(request)
        locale = context.locale_for(request, session)
        archived = request.query_params.get("archived") == "1"
        view_items = context.repository.catalog_items(
            locale=locale,
            archived=archived,
            collection_filter=request.query_params.get("collection"),
        )
        response = context.render(
            "catalog.html",
            locale=locale,
            session=session,
            items=view_items,
            archived=archived,
        )
        if fresh:
            context.set_session(response, session)
        return response

    @router.post("/ui/collections", response_class=HTMLResponse)
    async def create_collection(request: Request) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        _, form = checked
        name = form.get("name", "").strip()
        if not name:
            return context.ui_error(request, "collection_name_required", 422)
        context.repository.create_collection(name)
        return context.redirect()

    @router.post("/ui/locale")
    async def set_locale(request: Request) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        session, form = checked
        session["locale"] = resolve_locale(form.get("locale"), None)
        response = context.redirect(request.headers.get("referer", "/"))
        context.set_session(response, session)
        return response

    async def item_action(
        request: Request,
        item_id: str,
        action: Literal["archive", "restore", "move"],
    ) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        _, form = checked
        result = context.repository.change_item(item_id, action, form.get("collection_id") or None)
        if result == "item_missing":
            return context.ui_error(request, "media_item_not_found", 404)
        if result == "collection_unavailable":
            return context.ui_error(request, "collection_unavailable", 422)
        return context.redirect(f"/items/{item_id}")

    async def collection_action(
        request: Request, collection_id: str, *, restore: bool
    ) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        if not context.repository.change_collection(collection_id, restore=restore):
            return context.ui_error(request, "collection_not_found", 404)
        return context.redirect("/?archived=1" if not restore else "/")

    @router.post("/ui/collections/{collection_id}/archive")
    async def archive_collection(request: Request, collection_id: str) -> HTMLResponse:
        return await collection_action(request, collection_id, restore=False)

    @router.post("/ui/collections/{collection_id}/restore")
    async def restore_collection(request: Request, collection_id: str) -> HTMLResponse:
        return await collection_action(request, collection_id, restore=True)

    @router.post("/ui/items/{item_id}/archive")
    async def archive_item(request: Request, item_id: str) -> HTMLResponse:
        return await item_action(request, item_id, "archive")

    @router.post("/ui/items/{item_id}/restore")
    async def restore_item(request: Request, item_id: str) -> HTMLResponse:
        return await item_action(request, item_id, "restore")

    @router.post("/ui/items/{item_id}/move")
    async def move_item(request: Request, item_id: str) -> HTMLResponse:
        return await item_action(request, item_id, "move")

    @router.get("/ui/items/{item_id}/tabs/acquisitions", response_class=HTMLResponse)
    async def acquisition_fragment(request: Request, item_id: str) -> HTMLResponse:
        session, _ = context.session_for(request)
        locale = context.locale_for(request, session)
        body = context.templates.get_template("fragments/acquisitions.html").render(
            acquisitions=context.repository.acquisitions(item_id),
            csrf=session["csrf"],
            _=translation(locale).gettext,
            error_label=lambda code: message_for(code, locale),
            status_label=lambda status: acquisition_status_label(status, locale),
        )
        return HTMLResponse(body, headers={"Vary": "HX-Request"})

    @router.get("/items/{item_id}", response_class=HTMLResponse)
    async def item_detail(request: Request, item_id: str) -> HTMLResponse:
        session, fresh = context.session_for(request)
        locale = context.locale_for(request, session)
        detail = context.repository.item_detail(item_id)
        if detail is None:
            return context.ui_error(request, "media_item_not_found", 404)
        view_item, metadata = detail
        gettext = translation(locale).gettext
        feedback: str | None = None
        if request.query_params.get("saved") == "1":
            feedback = gettext("Title saved.")
        elif request.query_params.get("duplicate") == "1":
            feedback = gettext("This title already exists.")
        elif acquisition_status := request.query_params.get("acquisition"):
            feedback = acquisition_status_label(acquisition_status, locale)
        elif reconciled_status := request.query_params.get("reconciled"):
            feedback = acquisition_status_label(reconciled_status, locale)
        response = context.render(
            "detail.html",
            locale=locale,
            session=session,
            item=view_item,
            metadata=metadata,
            feedback=feedback,
        )
        if fresh:
            context.set_session(response, session)
        return response

    return router
