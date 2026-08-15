"""Metadata-provider and structured Manual browser routes."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from .domain import CatalogService, RevisionInput
from .manual import ManualCatalogService
from .models import MediaItem
from .modules.manual import ManualProvider
from .sdk.types import NormalizedMetadata
from .ui_context import UIContext
from .ui_i18n import code_for_exception, media_kind_label
from .ui_manual import manual_form_view, structured_manual_document
from .ui_security import resolve_locale, translation


def metadata_router(context: UIContext) -> APIRouter:
    router = APIRouter()

    @router.get("/add", response_class=HTMLResponse)
    async def add_page(request: Request) -> HTMLResponse:
        session, fresh = context.session_for(request)
        locale = context.locale_for(request, session)
        response = context.render("add.html", locale=locale, session=session)
        if fresh:
            context.set_session(response, session)
        return response

    @router.post("/ui/metadata/search", response_class=HTMLResponse)
    async def metadata_search(request: Request) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        session, form = checked
        metadata_locale = resolve_locale(form.get("metadata_locale"), None)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for key, provider in context.runtime.metadata_providers().items():
            results: list[dict[str, Any]] = []
            try:
                provider_results = provider.search(form.get("query", "").strip(), metadata_locale)
            except Exception as error:
                return context.ui_error(
                    request,
                    code_for_exception(error, "metadata_provider_unavailable"),
                    422,
                )
            for result in provider_results:
                token = secrets.token_urlsafe(32)
                context.metadata_selections[token] = result
                results.append({"token": token, "result": result})
            if results:
                grouped[key] = results
        locale = context.locale_for(request, session)
        body = context.templates.get_template("fragments/provider_results.html").render(
            grouped=grouped,
            csrf=session["csrf"],
            _=translation(locale).gettext,
            kind_label=lambda kind: media_kind_label(kind, locale),
        )
        return HTMLResponse(body, headers={"Vary": "HX-Request"})

    @router.post("/ui/metadata/confirm")
    async def confirm_metadata(request: Request) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        session, form = checked
        token = form.get("selection_token", "")
        result = context.metadata_selections.get(token)
        if result is None:
            return context.ui_error(request, "metadata_selection_expired", 410)
        provider = context.runtime.metadata_provider(result.provider_key).value
        if provider is None:
            return context.ui_error(request, "metadata_provider_unavailable", 422)
        with context.sessions() as database:
            catalog = CatalogService(database)
            item, created = catalog.get_or_create_item(
                result.provider_key, result.external_id, result.kind
            )
            if not created:
                context.metadata_selections.pop(token, None)
                return context.redirect(f"/items/{item.id}?duplicate=1")
            similar = catalog.find_similar(
                result.title, result.year, excluding_provider=result.provider_key
            )
            if similar and form.get("confirm_similar") != "yes":
                database.rollback()
                body = context.templates.get_template("fragments/similarity_warning.html").render(
                    result=result,
                    selection_token=token,
                    csrf=form["csrf"],
                    similar=similar,
                    _=translation(context.locale_for(request, session)).gettext,
                )
                return HTMLResponse(body, 200)
            now = datetime.now(UTC)
            try:
                raw = provider.fetch(result.kind.value, result.external_id, result.locale)
                normalized = provider.normalize(
                    raw, result.kind.value, result.external_id, result.locale
                )
                catalog.add_revision(
                    item,
                    RevisionInput(
                        normalized=normalized,
                        raw_payload=raw,
                        retention=provider.retention_for(now),
                        created_at=now,
                    ),
                )
            except Exception as error:
                database.rollback()
                return context.ui_error(
                    request,
                    code_for_exception(error, "metadata_provider_unavailable"),
                    422,
                )
            context.metadata_selections.pop(token, None)
            return context.redirect(f"/items/{item.id}?saved=1")

    @router.post("/ui/manual/import")
    async def manual_import(request: Request) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        _, form = checked
        try:
            payload = json.loads(form.get("document", ""))
            if not isinstance(payload, dict):
                raise ValueError
            with context.sessions() as database:
                item = ManualCatalogService(CatalogService(database), ManualProvider()).import_json(
                    payload, confirm_existing=form.get("confirm_existing") == "yes"
                )
            return context.redirect(f"/items/{item.id}?saved=1")
        except Exception:
            return context.ui_error(request, "manual_import_invalid", 422)

    @router.get("/add/manual", response_class=HTMLResponse)
    async def manual_create_page(request: Request) -> HTMLResponse:
        session, fresh = context.session_for(request)
        locale = context.locale_for(request, session)
        response = context.render(
            "manual_editor.html",
            locale=locale,
            session=session,
            manual=manual_form_view(None),
        )
        if fresh:
            context.set_session(response, session)
        return response

    @router.get("/items/{item_id}/edit", response_class=HTMLResponse)
    async def manual_edit_page(request: Request, item_id: str) -> HTMLResponse:
        session, fresh = context.session_for(request)
        locale = context.locale_for(request, session)
        with context.sessions() as database:
            item = database.get(MediaItem, item_id)
            if (
                item is None
                or item.provider_key != "manual"
                or item.current_revision is None
                or item.current_revision.effective_payload is None
            ):
                return context.ui_error(request, "manual_item_not_found", 404)
            metadata = NormalizedMetadata.model_validate(item.current_revision.effective_payload)
            external_id = item.external_id
        response = context.render(
            "manual_editor.html",
            locale=locale,
            session=session,
            manual=manual_form_view(metadata, external_id),
        )
        if fresh:
            context.set_session(response, session)
        return response

    @router.post("/ui/manual/save")
    async def manual_save(request: Request) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        session, form = checked
        try:
            document = structured_manual_document(form)
            external_id = document.get("external_id")
            if external_id:
                with context.sessions() as database:
                    existing = database.scalar(
                        select(MediaItem).where(
                            MediaItem.provider_key == "manual",
                            MediaItem.external_id == external_id,
                        )
                    )
                if existing is not None:
                    token = secrets.token_urlsafe(32)
                    context.manual_drafts[token] = document
                    body = context.templates.get_template(
                        "fragments/manual_confirmation.html"
                    ).render(
                        csrf=session["csrf"],
                        draft_token=token,
                        _=translation(context.locale_for(request, session)).gettext,
                    )
                    return HTMLResponse(body, 200)
            with context.sessions() as database:
                item = ManualCatalogService(CatalogService(database), ManualProvider()).import_json(
                    document
                )
            return context.redirect(f"/items/{item.id}?saved=1")
        except Exception:
            return context.ui_error(request, "manual_import_invalid", 422)

    @router.post("/ui/manual/confirm")
    async def manual_confirm(request: Request) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        _, form = checked
        document = context.manual_drafts.pop(form.get("draft_token", ""), None)
        if document is None:
            return context.ui_error(request, "manual_draft_expired", 410)
        try:
            with context.sessions() as database:
                item = ManualCatalogService(CatalogService(database), ManualProvider()).import_json(
                    document, confirm_existing=True
                )
            return context.redirect(f"/items/{item.id}?saved=1")
        except Exception:
            return context.ui_error(request, "manual_import_invalid", 422)

    @router.post("/ui/items/{item_id}/manual/csv")
    async def manual_csv(request: Request, item_id: str) -> HTMLResponse:
        checked = await context.checked_form(request)
        if checked is None:
            return context.denied(request)
        _, form = checked
        try:
            with context.sessions() as database:
                ManualCatalogService(CatalogService(database), ManualProvider()).import_episode_csv(
                    item_id, form.get("content", "")
                )
            return context.redirect(f"/items/{item_id}?saved=1")
        except Exception:
            return context.ui_error(request, "manual_import_invalid", 422)

    return router
