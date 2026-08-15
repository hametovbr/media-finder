"""Port-only composition for the bundled server-rendered interface."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from media_finder_control import (
    BrowserSecurityPort,
    BrowserSession,
    ControlFailure,
    Locale,
    ManualDocumentV1,
    PageRequest,
)
from media_finder_control.models import (
    AcquisitionSubmissionRequest,
    DownloadDestination,
    EpisodeImportRequest,
    ManualImportRequest,
    ManualImportResult,
    MediaItemOperation,
    MetadataSearchRequest,
    MetadataSelectionRequest,
    ReleaseSearchRequest,
)
from media_finder_control.ports import ControlGateway

from .forms import FormBodyTooLarge, decode_form
from .i18n import acquisition_status_label, media_kind_label, message_for, translation
from .manual import editable_document, form_view, structured_document

SESSION_COOKIE = "mf_session"
PACKAGE_ROOT = Path(__file__).parent


@dataclass(frozen=True, slots=True)
class BuiltinUIOptions:
    secure_cookie: bool = False


def _kind_label(value: object, locale: Locale) -> str:
    return media_kind_label(str(value), locale.value)


def _status_label(value: object, locale: Locale) -> str:
    return acquisition_status_label(str(value), locale.value)


def create_builtin_ui(
    *,
    gateway: ControlGateway,
    security: BrowserSecurityPort,
    options: BuiltinUIOptions | None = None,
) -> FastAPI:
    """Create the bundled UI without persistence or integration ownership."""

    selected = options or BuiltinUIOptions()
    templates = Environment(
        loader=FileSystemLoader(PACKAGE_ROOT / "templates"),
        autoescape=select_autoescape(("html", "xml")),
    )
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    async def session_for(request: Request) -> BrowserSession:
        return await security.load_session(
            cookie=request.cookies.get(SESSION_COOKIE),
            accept_language=request.headers.get("accept-language"),
        )

    async def render(
        request: Request,
        template: str,
        session: BrowserSession,
        status_code: int = 200,
        **values: object,
    ) -> HTMLResponse:
        collections = await gateway.list_collections(page=PageRequest(), archived=False)
        archived = await gateway.list_collections(page=PageRequest(), archived=True)
        translator = translation(session.ui_locale.value).gettext
        body = templates.get_template(template).render(
            locale=session.ui_locale.value,
            metadata_locale=session.metadata_locale.value,
            csrf=session.csrf_token,
            collections=collections.items,
            archived_collections=archived.items,
            _=translator,
            kind_label=lambda value: _kind_label(value, session.ui_locale),
            status_label=lambda value: _status_label(value, session.ui_locale),
            **values,
        )
        response = HTMLResponse(body, status_code=status_code)
        if session.is_new:
            response.set_cookie(
                SESSION_COOKIE,
                await security.serialize_session(session=session),
                httponly=True,
                samesite="lax",
                secure=selected.secure_cookie,
                path="/",
            )
        return response

    async def checked_form(
        request: Request,
    ) -> tuple[BrowserSession, dict[str, str]] | None:
        session = await session_for(request)
        form = await decode_form(request)
        if session.is_new or not await security.validate_csrf(
            session=session,
            token=form.get("csrf"),
        ):
            return None
        return session, form

    async def ui_error(request: Request, code: str, status_code: int) -> HTMLResponse:
        session = await session_for(request)
        message = message_for(code, session.ui_locale.value)
        return HTMLResponse(
            f'<p role="alert" aria-live="assertive" data-error-code="{code}">'
            f"{message} <code>{code}</code></p>",
            status_code=status_code,
        )

    async def set_session(response: RedirectResponse, session: BrowserSession) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            await security.serialize_session(session=session),
            httponly=True,
            samesite="lax",
            secure=selected.secure_cookie,
            path="/",
        )

    def safe_referer(request: Request) -> str:
        supplied = request.headers.get("referer")
        if not supplied:
            return "/"
        parsed = urlsplit(supplied)
        if parsed.scheme != request.url.scheme or parsed.netloc != request.headers.get("host"):
            return "/"
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")

    @app.exception_handler(FormBodyTooLarge)
    async def form_too_large(request: Request, _: FormBodyTooLarge) -> HTMLResponse:
        return await ui_error(request, "ui_form_too_large", 413)

    @app.get("/", response_class=HTMLResponse)
    async def catalog(request: Request) -> HTMLResponse:
        session = await session_for(request)
        archived = request.query_params.get("archived") == "1"
        collection = request.query_params.get("collection")
        page = await gateway.list_media_items(
            locale=session.ui_locale,
            page=PageRequest(),
            collection_id=(None if collection in {None, "uncategorized"} else collection),
            uncategorized=collection == "uncategorized",
            archived=archived,
        )
        return await render(
            request,
            "catalog.html",
            session,
            items=page.items,
            archived=archived,
        )

    @app.post("/ui/collections")
    async def create_collection(request: Request) -> Response:
        checked = await checked_form(request)
        if checked is None:
            return await ui_error(request, "csrf_invalid", 403)
        _, form = checked
        name = form.get("name", "").strip()
        if not name:
            return await ui_error(request, "collection_name_required", 422)
        await gateway.create_collection(name=name)
        return RedirectResponse("/", status_code=303)

    @app.post("/ui/locale")
    async def set_locale(request: Request) -> Response:
        checked = await checked_form(request)
        if checked is None:
            return await ui_error(request, "csrf_invalid", 403)
        session, form = checked
        try:
            locale = Locale(form.get("locale", ""))
        except ValueError:
            locale = Locale.EN
        metadata = session.metadata_locale if session.metadata_locale_explicit else locale
        changed = session.model_copy(
            update={"ui_locale": locale, "metadata_locale": metadata, "is_new": False}
        )
        response = RedirectResponse(safe_referer(request), status_code=303)
        await set_session(response, changed)
        return response

    @app.post("/ui/metadata-locale")
    async def set_metadata_locale(request: Request) -> Response:
        checked = await checked_form(request)
        if checked is None:
            return await ui_error(request, "csrf_invalid", 403)
        session, form = checked
        try:
            locale = Locale(form.get("metadata_locale", ""))
        except ValueError:
            locale = Locale.EN
        changed = session.model_copy(
            update={
                "metadata_locale": locale,
                "metadata_locale_explicit": True,
                "is_new": False,
            }
        )
        response = RedirectResponse(safe_referer(request), status_code=303)
        await set_session(response, changed)
        return response

    async def collection_change(
        request: Request,
        collection_id: str,
        archived: bool,
    ) -> Response:
        if await checked_form(request) is None:
            return await ui_error(request, "csrf_invalid", 403)
        try:
            await gateway.change_collection(collection_id=collection_id, archived=archived)
        except Exception:
            return await ui_error(request, "collection_not_found", 404)
        return RedirectResponse("/?archived=1" if archived else "/", status_code=303)

    @app.post("/ui/collections/{collection_id}/archive")
    async def archive_collection(request: Request, collection_id: str) -> Response:
        return await collection_change(request, collection_id, True)

    @app.post("/ui/collections/{collection_id}/restore")
    async def restore_collection(request: Request, collection_id: str) -> Response:
        return await collection_change(request, collection_id, False)

    async def item_change(
        request: Request,
        item_id: str,
        operation: MediaItemOperation,
    ) -> Response:
        checked = await checked_form(request)
        if checked is None:
            return await ui_error(request, "csrf_invalid", 403)
        session, form = checked
        try:
            current = await gateway.get_media_item(item_id=item_id, locale=session.ui_locale)
            await gateway.change_media_item(
                item_id=item_id,
                collection_id=(
                    form.get("collection_id") or None
                    if operation is MediaItemOperation.MOVE
                    else current.collection_id
                ),
                archived={
                    MediaItemOperation.ARCHIVE: True,
                    MediaItemOperation.RESTORE: False,
                    MediaItemOperation.MOVE: None,
                }[operation],
                locale=session.ui_locale,
            )
        except Exception:
            return await ui_error(request, "collection_unavailable", 422)
        return RedirectResponse(f"/items/{item_id}", status_code=303)

    @app.post("/ui/items/{item_id}/archive")
    async def archive_item(request: Request, item_id: str) -> Response:
        return await item_change(request, item_id, MediaItemOperation.ARCHIVE)

    @app.post("/ui/items/{item_id}/restore")
    async def restore_item(request: Request, item_id: str) -> Response:
        return await item_change(request, item_id, MediaItemOperation.RESTORE)

    @app.post("/ui/items/{item_id}/move")
    async def move_item(request: Request, item_id: str) -> Response:
        return await item_change(request, item_id, MediaItemOperation.MOVE)

    @app.get("/items/{item_id}", response_class=HTMLResponse)
    async def item_detail(request: Request, item_id: str) -> HTMLResponse:
        session = await session_for(request)
        try:
            item = await gateway.get_media_item(item_id=item_id, locale=session.ui_locale)
        except Exception:
            return await ui_error(request, "media_item_not_found", 404)
        feedback = None
        translator = translation(session.ui_locale.value).gettext
        if request.query_params.get("saved") == "1":
            feedback = translator("Title saved.")
        elif request.query_params.get("duplicate") == "1":
            feedback = translator("This title already exists.")
        elif acquisition := request.query_params.get("acquisition"):
            feedback = _status_label(acquisition, session.ui_locale)
        elif reconciled := request.query_params.get("reconciled"):
            feedback = _status_label(reconciled, session.ui_locale)
        return await render(
            request,
            "detail.html",
            session,
            item=item,
            metadata=item.metadata.model_dump(mode="json"),
            feedback=feedback,
        )

    @app.get("/ui/items/{item_id}/tabs/acquisitions", response_class=HTMLResponse)
    async def acquisition_fragment(request: Request, item_id: str) -> HTMLResponse:
        session = await session_for(request)
        try:
            item = await gateway.get_media_item(item_id=item_id, locale=session.ui_locale)
        except Exception:
            return await ui_error(request, "media_item_not_found", 404)
        translator = translation(session.ui_locale.value).gettext
        body = templates.get_template("fragments/acquisitions.html").render(
            acquisitions=item.acquisitions,
            csrf=session.csrf_token,
            _=translator,
            error_label=lambda code: message_for(code, session.ui_locale.value),
            status_label=lambda value: _status_label(value, session.ui_locale),
        )
        return HTMLResponse(body, headers={"Vary": "HX-Request"})

    @app.get("/add", response_class=HTMLResponse)
    async def add_page(request: Request) -> HTMLResponse:
        session = await session_for(request)
        return await render(request, "add.html", session)

    @app.post("/ui/metadata/search", response_class=HTMLResponse)
    async def metadata_search(request: Request) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return await ui_error(request, "csrf_invalid", 403)
        session, form = checked
        try:
            results = await gateway.search_metadata(
                request=MetadataSearchRequest(
                    query=form.get("query", "").strip(),
                    locale=session.metadata_locale,
                )
            )
        except ControlFailure as error:
            return await ui_error(request, error.error.code, error.status)
        grouped: dict[str, list[dict[str, object]]] = {}
        for result in results:
            grouped.setdefault(result.provider_key, []).append(
                {"token": result.token, "result": result}
            )
        body = templates.get_template("fragments/provider_results.html").render(
            grouped=grouped,
            csrf=session.csrf_token,
            _=translation(session.ui_locale.value).gettext,
            kind_label=lambda value: _kind_label(value, session.ui_locale),
        )
        return HTMLResponse(body, headers={"Vary": "HX-Request"})

    @app.post("/ui/metadata/confirm")
    async def metadata_confirm(request: Request) -> Response:
        checked = await checked_form(request)
        if checked is None:
            return await ui_error(request, "csrf_invalid", 403)
        session, form = checked
        try:
            result = await gateway.select_metadata(
                token=form.get("selection_token", ""),
                request=MetadataSelectionRequest(
                    confirm_similarity=form.get("confirm_similar") == "yes"
                ),
                locale=session.metadata_locale,
            )
        except ControlFailure as error:
            if error.error.code == "confirmation_required":
                token = error.error.details.get("confirmation_token")
                body = templates.get_template("fragments/similarity_warning.html").render(
                    selection_token=token,
                    csrf=session.csrf_token,
                    _=translation(session.ui_locale.value).gettext,
                )
                return HTMLResponse(body)
            code = (
                "metadata_selection_expired"
                if error.error.code == "selection_expired"
                else error.error.code
            )
            return await ui_error(request, code, error.status)
        suffix = "saved=1" if result.created else "duplicate=1"
        return RedirectResponse(f"/items/{result.item.id}?{suffix}", status_code=303)

    def manual_confirmation(session: BrowserSession, token: str) -> HTMLResponse:
        body = templates.get_template("fragments/manual_confirmation.html").render(
            csrf=session.csrf_token,
            draft_token=token,
            _=translation(session.ui_locale.value).gettext,
        )
        return HTMLResponse(body)

    async def manual_result(
        request: Request,
        session: BrowserSession,
        result: ManualImportResult,
    ) -> Response:
        if result.confirmation_token is not None:
            return manual_confirmation(session, result.confirmation_token)
        if result.item is None:
            return await ui_error(request, "manual_import_invalid", 422)
        return RedirectResponse(f"/items/{result.item.id}?saved=1", status_code=303)

    @app.post("/ui/manual/import")
    async def manual_import(request: Request) -> Response:
        checked = await checked_form(request)
        if checked is None:
            return await ui_error(request, "csrf_invalid", 403)
        session, form = checked
        try:
            payload = json.loads(form.get("document", ""))
            document = ManualDocumentV1.model_validate(payload)
            result = await gateway.import_manual(request=ManualImportRequest(document=document))
        except (ValueError, ControlFailure, json.JSONDecodeError):
            return await ui_error(request, "manual_import_invalid", 422)
        return await manual_result(request, session, result)

    @app.get("/add/manual", response_class=HTMLResponse)
    async def manual_create_page(request: Request) -> HTMLResponse:
        session = await session_for(request)
        return await render(
            request,
            "manual_editor.html",
            session,
            manual=form_view(None, session.metadata_locale),
        )

    @app.get("/items/{item_id}/edit", response_class=HTMLResponse)
    async def manual_edit_page(request: Request, item_id: str) -> HTMLResponse:
        session = await session_for(request)
        try:
            item = await gateway.get_media_item(item_id=item_id, locale=session.metadata_locale)
            if item.provider_key != "manual":
                raise ValueError
            document = editable_document(
                item.metadata,
                external_id=item.external_id,
                locale=session.metadata_locale,
            )
        except Exception:
            return await ui_error(request, "manual_item_not_found", 404)
        return await render(
            request,
            "manual_editor.html",
            session,
            manual=form_view(document, session.metadata_locale, item_id=item.id),
        )

    @app.post("/ui/manual/save")
    async def manual_save(request: Request) -> Response:
        checked = await checked_form(request)
        if checked is None:
            return await ui_error(request, "csrf_invalid", 403)
        session, form = checked
        try:
            current = None
            item_id = form.get("item_id") or None
            if item_id is not None:
                item = await gateway.get_media_item(
                    item_id=item_id,
                    locale=session.metadata_locale,
                )
                current = editable_document(
                    item.metadata,
                    external_id=item.external_id,
                    locale=session.metadata_locale,
                )
            document = structured_document(form, current)
            result = (
                await gateway.edit_manual(item_id=item_id, document=document)
                if item_id is not None
                else await gateway.import_manual(request=ManualImportRequest(document=document))
            )
        except Exception:
            return await ui_error(request, "manual_import_invalid", 422)
        return await manual_result(request, session, result)

    @app.post("/ui/manual/confirm")
    async def manual_confirm(request: Request) -> Response:
        checked = await checked_form(request)
        if checked is None:
            return await ui_error(request, "csrf_invalid", 403)
        session, form = checked
        try:
            result = await gateway.confirm_manual(token=form.get("draft_token", ""))
        except ControlFailure as error:
            return await ui_error(
                request,
                "manual_draft_expired"
                if error.error.code == "selection_expired"
                else error.error.code,
                error.status,
            )
        return await manual_result(request, session, result)

    @app.post("/ui/items/{item_id}/manual/csv")
    async def manual_csv(request: Request, item_id: str) -> Response:
        checked = await checked_form(request)
        if checked is None:
            return await ui_error(request, "csrf_invalid", 403)
        session, form = checked
        try:
            await gateway.import_episodes(
                item_id=item_id,
                request=EpisodeImportRequest(csv=form.get("content", "")),
                locale=session.metadata_locale,
            )
        except ControlFailure as error:
            return await ui_error(request, error.error.code, error.status)
        return RedirectResponse(f"/items/{item_id}?saved=1", status_code=303)

    @app.get("/items/{item_id}/releases", response_class=HTMLResponse)
    async def release_page(request: Request, item_id: str) -> HTMLResponse:
        session = await session_for(request)
        try:
            await gateway.get_media_item(item_id=item_id, locale=session.ui_locale)
        except ControlFailure as error:
            return await ui_error(request, error.error.code, error.status)
        return await render(
            request,
            "release.html",
            session,
            item_id=item_id,
            idempotency_key=secrets.token_urlsafe(24),
        )

    @app.post("/ui/items/{item_id}/releases/search", response_class=HTMLResponse)
    async def release_search(request: Request, item_id: str) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return await ui_error(request, "csrf_invalid", 403)
        session, form = checked
        if not form.get("query", "").strip():
            return await ui_error(request, "release_search_query_required", 422)
        try:
            indexers = tuple(
                int(value) for value in form.get("indexer", "").split(",") if value.strip()
            )
            results = await gateway.search_releases(
                item_id=item_id,
                request=ReleaseSearchRequest(
                    query=form.get("query", "").strip(),
                    indexer_ids=indexers,
                ),
            )
        except (ValueError, ControlFailure) as error:
            if isinstance(error, ControlFailure):
                return await ui_error(request, error.error.code, error.status)
            return await ui_error(request, "prowlarr_search_failed", 422)
        body = templates.get_template("fragments/release_results.html").render(
            results=results,
            item_id=item_id,
            csrf=session.csrf_token,
            _=translation(session.ui_locale.value).gettext,
        )
        return HTMLResponse(body, headers={"Vary": "HX-Request"})

    async def destinations_response(request: Request) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return await ui_error(request, "csrf_invalid", 403)
        session, _ = checked
        try:
            destinations = await gateway.list_destinations()
            error_code = None
            status_code = 200
        except ControlFailure as error:
            destinations = ()
            error_code = error.error.code
            status_code = error.status
        body = templates.get_template("fragments/destinations.html").render(
            destinations=destinations,
            error_code=error_code,
            error_label=lambda code: message_for(code, session.ui_locale.value),
            _=translation(session.ui_locale.value).gettext,
        )
        return HTMLResponse(body, status_code=status_code, headers={"Vary": "HX-Request"})

    @app.post("/ui/qbittorrent/destinations", response_class=HTMLResponse)
    async def destinations(request: Request) -> HTMLResponse:
        return await destinations_response(request)

    @app.post("/ui/items/{item_id}/acquisitions")
    async def submit_acquisition(request: Request, item_id: str) -> Response:
        checked = await checked_form(request)
        if checked is None:
            return await ui_error(request, "csrf_invalid", 403)
        session, form = checked
        try:
            acquisition = await gateway.submit_acquisition(
                request=AcquisitionSubmissionRequest(
                    media_item_id=item_id,
                    release_token=form.get("release_token", ""),
                    destination=form.get("destination", ""),
                    idempotency_key=form.get("idempotency_key", ""),
                )
            )
        except ControlFailure as error:
            if error.error.code == "download_destination_unavailable":
                current = error.error.details.get("destinations", [])
                destinations = tuple(
                    DownloadDestination.model_validate(value)
                    for value in (current if isinstance(current, list) else [])
                    if isinstance(value, dict)
                )
                body = templates.get_template("fragments/acquisition_retry.html").render(
                    item_id=item_id,
                    destinations=destinations,
                    error_code=error.error.code,
                    error_label=lambda code: message_for(code, session.ui_locale.value),
                    csrf=session.csrf_token,
                    release_token=form.get("release_token", ""),
                    idempotency_key=form.get("idempotency_key", ""),
                    _=translation(session.ui_locale.value).gettext,
                )
                return HTMLResponse(body, status_code=409, headers={"Vary": "HX-Request"})
            return await ui_error(request, error.error.code, error.status)
        return RedirectResponse(
            f"/items/{item_id}?acquisition={acquisition.status.value}", status_code=303
        )

    @app.post("/ui/acquisitions/{acquisition_id}/reconcile")
    async def reconcile_acquisition(request: Request, acquisition_id: str) -> Response:
        if await checked_form(request) is None:
            return await ui_error(request, "csrf_invalid", 403)
        try:
            acquisition = await gateway.reconcile_acquisition(acquisition_id=acquisition_id)
        except ControlFailure as error:
            return await ui_error(request, error.error.code, error.status)
        return RedirectResponse(
            f"/items/{acquisition.media_item_id}?reconciled={acquisition.status.value}",
            status_code=303,
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        session = await session_for(request)
        diagnostics = await gateway.integration_diagnostics()
        return await render(
            request,
            "settings.html",
            session,
            diagnostics=diagnostics,
        )

    @app.get("/about", response_class=HTMLResponse)
    async def about_page(request: Request) -> HTMLResponse:
        session = await session_for(request)
        about = await gateway.about()
        return await render(
            request,
            "about.html",
            session,
            attributions=about.attributions,
        )

    app.mount("/static", StaticFiles(directory=PACKAGE_ROOT / "static"), name="static")
    app.state.gateway = gateway
    return app
