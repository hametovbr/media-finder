"""Server-rendered browser interface with signed session state."""

from __future__ import annotations

import hmac
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select

from .acquisition import (
    AcquisitionRequest,
    AcquisitionService,
    ClientLoader,
    create_download_client_instance,
)
from .config import EnvReference, resolve_env_reference, safe_url_origin
from .db import create_database, session_factory
from .domain import CatalogService, RevisionInput
from .manual import ManualCatalogService
from .models import DownloadClientInstance, MediaItem
from .modules.manual import ManualProvider
from .prowlarr import ProwlarrAdapter
from .sdk.protocols import MetadataProvider
from .sdk.settings import describe_settings
from .ui_repository import UIRepository
from .ui_security import (
    SESSION_COOKIE,
    SessionSigner,
    decode_form,
    error_message,
    resolve_locale,
    translation,
)

__all__ = ["SessionSigner", "create_ui_app", "error_message", "resolve_locale"]

TEMPLATE_ROOT = Path(__file__).with_name("templates")
STATIC_ROOT = Path(__file__).with_name("static")


def create_ui_app(
    database_url: str,
    *,
    session_secret_reference: str,
    secure_cookie: bool = False,
    providers: dict[str, MetadataProvider] | None = None,
    prowlarr: ProwlarrAdapter | None = None,
    client_loader: ClientLoader | None = None,
    **_: Any,
) -> FastAPI:
    engine = create_database(database_url)
    secret_value = resolve_env_reference(EnvReference(value=session_secret_reference))
    signer = SessionSigner(secret_value.get_secret_value().encode())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.state.engine = engine
    app.state.session_signer = signer
    sessions = session_factory(engine)
    repository = UIRepository(sessions)
    app.state.sessions = sessions
    app.state.providers = dict(providers or {})
    app.state.prowlarr = prowlarr
    app.state.client_loader = client_loader
    app.state.metadata_selections = {}
    templates = Environment(
        loader=FileSystemLoader(TEMPLATE_ROOT),
        autoescape=select_autoescape(("html", "xml")),
        enable_async=False,
    )
    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    def session_for(request: Request) -> tuple[dict[str, str], bool]:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            try:
                return signer.loads(token), False
            except ValueError:
                pass
        return {"csrf": secrets.token_urlsafe(32)}, True

    def set_session(response: HTMLResponse, session: dict[str, str]) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            signer.dumps(session),
            httponly=True,
            samesite="lax",
            secure=secure_cookie,
            path="/",
        )

    def render(
        name: str,
        *,
        locale: str,
        session: dict[str, str],
        status_code: int = 200,
        **context: Any,
    ) -> HTMLResponse:
        body = templates.get_template(name).render(
            locale=locale,
            csrf=session["csrf"],
            collections=repository.active_collections(),
            _=translation(locale).gettext,
            **context,
        )
        return HTMLResponse(body, status_code=status_code)

    async def checked_form(request: Request) -> tuple[dict[str, str], dict[str, str]] | None:
        session, fresh = session_for(request)
        form = await decode_form(request)
        if fresh or not hmac.compare_digest(form.get("csrf", ""), session["csrf"]):
            return None
        return session, form

    def denied() -> HTMLResponse:
        return HTMLResponse(
            '<p role="alert">Request rejected. <code>csrf_invalid</code></p>',
            status_code=403,
        )

    def redirect(location: str = "/") -> HTMLResponse:
        return cast(HTMLResponse, RedirectResponse(location, status_code=303))

    def locale_for(request: Request, session: dict[str, str]) -> str:
        return resolve_locale(session.get("locale"), request.headers.get("accept-language"))

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        session, fresh = session_for(request)
        locale = locale_for(request, session)
        archived = request.query_params.get("archived") == "1"
        collection_filter = request.query_params.get("collection")
        view_items = repository.catalog_items(
            locale=locale, archived=archived, collection_filter=collection_filter
        )
        response = render("catalog.html", locale=locale, session=session, items=view_items)
        if fresh:
            set_session(response, session)
        return response

    @app.post("/ui/collections", response_class=HTMLResponse)
    async def create_collection(request: Request) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        _, form = checked
        name = form.get("name", "").strip()
        if not name:
            return HTMLResponse('<p role="alert">collection_name_required</p>', 422)
        repository.create_collection(name)
        return redirect()

    @app.post("/ui/locale")
    async def set_locale(request: Request) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        session, form = checked
        session["locale"] = resolve_locale(form.get("locale"), None)
        response = redirect(request.headers.get("referer", "/"))
        set_session(response, session)
        return response

    async def item_action(
        request: Request,
        item_id: str,
        action: Literal["archive", "restore", "move"],
    ) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        _, form = checked
        result = repository.change_item(item_id, action, form.get("collection_id") or None)
        if result == "item_missing":
            return HTMLResponse('<p role="alert">media_item_not_found</p>', 404)
        if result == "collection_unavailable":
            return HTMLResponse('<p role="alert">collection_unavailable</p>', 422)
        return redirect(f"/items/{item_id}")

    async def collection_action(
        request: Request, collection_id: str, *, restore: bool
    ) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        if not repository.change_collection(collection_id, restore=restore):
            return HTMLResponse('<p role="alert">collection_not_found</p>', 404)
        return redirect("/?archived=1" if not restore else "/")

    @app.post("/ui/collections/{collection_id}/archive")
    async def archive_collection(request: Request, collection_id: str) -> HTMLResponse:
        return await collection_action(request, collection_id, restore=False)

    @app.post("/ui/collections/{collection_id}/restore")
    async def restore_collection(request: Request, collection_id: str) -> HTMLResponse:
        return await collection_action(request, collection_id, restore=True)

    @app.post("/ui/items/{item_id}/archive")
    async def archive_item(request: Request, item_id: str) -> HTMLResponse:
        return await item_action(request, item_id, "archive")

    @app.post("/ui/items/{item_id}/restore")
    async def restore_item(request: Request, item_id: str) -> HTMLResponse:
        return await item_action(request, item_id, "restore")

    @app.post("/ui/items/{item_id}/move")
    async def move_item(request: Request, item_id: str) -> HTMLResponse:
        return await item_action(request, item_id, "move")

    @app.get("/ui/items/{item_id}/tabs/acquisitions", response_class=HTMLResponse)
    async def acquisition_fragment(request: Request, item_id: str) -> HTMLResponse:
        session, _ = session_for(request)
        locale = resolve_locale(session.get("locale"), request.headers.get("accept-language"))
        acquisitions = repository.acquisitions(item_id)
        body = templates.get_template("fragments/acquisitions.html").render(
            acquisitions=acquisitions,
            csrf=session["csrf"],
            _=translation(locale).gettext,
        )
        return HTMLResponse(body, headers={"Vary": "HX-Request"})

    @app.get("/add", response_class=HTMLResponse)
    async def add_page(request: Request) -> HTMLResponse:
        session, fresh = session_for(request)
        locale = locale_for(request, session)
        response = render("add.html", locale=locale, session=session)
        if fresh:
            set_session(response, session)
        return response

    @app.post("/ui/metadata/search", response_class=HTMLResponse)
    async def metadata_search(request: Request) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        session, form = checked
        query = form.get("query", "").strip()
        metadata_locale = resolve_locale(form.get("metadata_locale"), None)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for key, provider in app.state.providers.items():
            results: list[dict[str, Any]] = []
            for result in provider.search(query, metadata_locale):
                token = secrets.token_urlsafe(32)
                app.state.metadata_selections[token] = result
                results.append({"token": token, "result": result})
            if results:
                grouped[key] = results
        body = templates.get_template("fragments/provider_results.html").render(
            grouped=grouped,
            csrf=session["csrf"],
            _=translation(locale_for(request, session)).gettext,
        )
        return HTMLResponse(body, headers={"Vary": "HX-Request"})

    @app.post("/ui/metadata/confirm")
    async def confirm_metadata(request: Request) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        _, form = checked
        token = form.get("selection_token", "")
        result = app.state.metadata_selections.get(token)
        if result is None:
            return HTMLResponse('<p role="alert">metadata_selection_expired</p>', 410)
        provider = app.state.providers.get(result.provider_key)
        if provider is None:
            return HTMLResponse('<p role="alert">metadata_provider_unavailable</p>', 422)
        with sessions() as database:
            catalog = CatalogService(database)
            item, created = catalog.get_or_create_item(
                result.provider_key, result.external_id, result.kind
            )
            if not created:
                app.state.metadata_selections.pop(token, None)
                return redirect(f"/items/{item.id}?duplicate=1")
            similar = catalog.find_similar(
                result.title, result.year, excluding_provider=result.provider_key
            )
            if similar and form.get("confirm_similar") != "yes":
                database.rollback()
                return HTMLResponse(
                    templates.get_template("fragments/similarity_warning.html").render(
                        result=result, selection_token=token, csrf=form["csrf"], similar=similar
                    ),
                    409,
                )
            now = datetime.now(UTC)
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
            app.state.metadata_selections.pop(token, None)
            return redirect(f"/items/{item.id}?saved=1")

    @app.post("/ui/manual/import")
    async def manual_import(request: Request) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        _, form = checked
        try:
            payload = json.loads(form.get("document", ""))
            if not isinstance(payload, dict):
                raise ValueError
            with sessions() as database:
                item = ManualCatalogService(CatalogService(database), ManualProvider()).import_json(
                    payload, confirm_existing=form.get("confirm_existing") == "yes"
                )
            return redirect(f"/items/{item.id}?saved=1")
        except Exception:
            return HTMLResponse('<p role="alert">manual_import_invalid</p>', 422)

    @app.post("/ui/items/{item_id}/manual/csv")
    async def manual_csv(request: Request, item_id: str) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        _, form = checked
        try:
            with sessions() as database:
                ManualCatalogService(CatalogService(database), ManualProvider()).import_episode_csv(
                    item_id, form.get("content", "")
                )
            return redirect(f"/items/{item_id}?saved=1")
        except Exception:
            return HTMLResponse('<p role="alert">manual_import_invalid</p>', 422)

    @app.get("/items/{item_id}", response_class=HTMLResponse)
    async def item_detail(request: Request, item_id: str) -> HTMLResponse:
        session, fresh = session_for(request)
        locale = locale_for(request, session)
        detail = repository.item_detail(item_id)
        if detail is None:
            return HTMLResponse('<p role="alert">media_item_not_found</p>', 404)
        view_item, metadata = detail
        response = render(
            "detail.html",
            locale=locale,
            session=session,
            item=view_item,
            metadata=metadata,
        )
        if fresh:
            set_session(response, session)
        return response

    @app.post("/ui/items/{item_id}/releases/search", response_class=HTMLResponse)
    async def release_search(request: Request, item_id: str) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        session, form = checked
        if app.state.prowlarr is None:
            return HTMLResponse('<p role="alert">prowlarr_not_configured</p>', 422)
        filters = {"indexerIds": form["indexer"]} if form.get("indexer") else {}
        try:
            results = app.state.prowlarr.search(form.get("query", ""), filters)
        except Exception:
            return HTMLResponse('<p role="alert">prowlarr_search_failed</p>', 422)
        body = templates.get_template("fragments/release_results.html").render(
            results=results, item_id=item_id, csrf=session["csrf"]
        )
        return HTMLResponse(body, headers={"Vary": "HX-Request"})

    @app.get("/items/{item_id}/releases", response_class=HTMLResponse)
    async def release_page(request: Request, item_id: str) -> HTMLResponse:
        session, fresh = session_for(request)
        locale = locale_for(request, session)
        with sessions() as database:
            item = database.get(MediaItem, item_id)
            clients = list(
                database.scalars(
                    select(DownloadClientInstance).where(
                        DownloadClientInstance.archived_at.is_(None)
                    )
                )
            )
        if item is None:
            return HTMLResponse('<p role="alert">media_item_not_found</p>', 404)
        response = render(
            "release.html",
            locale=locale,
            session=session,
            item_id=item_id,
            clients=clients,
            idempotency_key=secrets.token_urlsafe(24),
        )
        if fresh:
            set_session(response, session)
        return response

    @app.post("/ui/clients/{client_id}/destinations", response_class=HTMLResponse)
    async def client_destinations(request: Request, client_id: str) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        if app.state.client_loader is None:
            return HTMLResponse('<p role="alert">download_client_unavailable</p>', 422)
        with sessions() as database:
            instance = database.get(DownloadClientInstance, client_id)
            if instance is None:
                return HTMLResponse('<p role="alert">download_client_not_found</p>', 404)
            destinations = app.state.client_loader(instance).list_destinations()
        body = templates.get_template("fragments/destinations.html").render(
            destinations=destinations
        )
        return HTMLResponse(body, headers={"Vary": "HX-Request"})

    @app.post("/ui/items/{item_id}/acquisitions")
    async def submit_acquisition(request: Request, item_id: str) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        _, form = checked
        if app.state.prowlarr is None or app.state.client_loader is None:
            return HTMLResponse('<p role="alert">acquisition_unavailable</p>', 422)
        with sessions() as database:
            item = database.get(MediaItem, item_id)
            if item is None or item.current_revision_id is None:
                return HTMLResponse('<p role="alert">media_item_not_found</p>', 404)
            service = AcquisitionService(database, app.state.prowlarr, app.state.client_loader)
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
        return redirect(f"/items/{item_id}?acquisition={acquisition.status}")

    @app.post("/ui/acquisitions/{acquisition_id}/reconcile")
    async def reconcile_acquisition(request: Request, acquisition_id: str) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        if app.state.prowlarr is None or app.state.client_loader is None:
            return HTMLResponse('<p role="alert">acquisition_unavailable</p>', 422)
        with sessions() as database:
            acquisition = AcquisitionService(
                database, app.state.prowlarr, app.state.client_loader
            ).reconcile(acquisition_id)
        return redirect(f"/items/{acquisition.media_item_id}")

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        session, fresh = session_for(request)
        locale = locale_for(request, session)
        provider_fields = {
            key: describe_settings(provider.config_model)
            for key, provider in app.state.providers.items()
        }
        clients = repository.clients()
        response = render(
            "settings.html",
            locale=locale,
            session=session,
            provider_fields=provider_fields,
            clients=clients,
            prowlarr_ready=app.state.prowlarr is not None,
            tmdb_ready=repository.has_setting("metadata_provider:tmdb"),
        )
        if fresh:
            set_session(response, session)
        return response

    @app.post("/ui/settings/providers/{provider_key}")
    async def save_provider_settings(request: Request, provider_key: str) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        _, form = checked
        provider = app.state.providers.get(provider_key)
        if provider is None:
            return HTMLResponse('<p role="alert">metadata_provider_not_found</p>', 404)
        try:
            payload = {key: value for key, value in form.items() if key != "csrf"}
            normalized = provider.config_model.model_validate(payload).model_dump(mode="json")
        except Exception:
            return HTMLResponse('<p role="alert">metadata_provider_configuration_invalid</p>', 422)
        repository.store_setting(f"metadata_provider:{provider_key}", normalized)
        return redirect("/settings?saved=1")

    @app.post("/ui/settings/prowlarr")
    async def save_prowlarr_settings(request: Request) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        _, form = checked
        base_url = form.get("base_url", "")
        try:
            reference = EnvReference(value=form.get("api_key_ref", ""))
            origin = safe_url_origin(base_url)
            if origin is None or origin != base_url.rstrip("/"):
                raise ValueError
        except Exception:
            return HTMLResponse('<p role="alert">prowlarr_configuration_invalid</p>', 422)
        repository.store_setting("prowlarr", {"base_url": origin, "api_key_ref": reference.value})
        return redirect("/settings?saved=1")

    @app.post("/ui/settings/clients")
    async def save_client_settings(request: Request) -> HTMLResponse:
        checked = await checked_form(request)
        if checked is None:
            return denied()
        _, form = checked
        try:
            config = {
                key: value
                for key, value in form.items()
                if key not in {"csrf", "name", "module_key"}
            }
            with sessions() as database:
                create_download_client_instance(
                    database,
                    name=form.get("name", ""),
                    module_key=form.get("module_key", ""),
                    config_payload=config,
                )
        except Exception:
            return HTMLResponse('<p role="alert">download_client_configuration_invalid</p>', 422)
        return redirect("/settings?saved=1")

    @app.get("/about", response_class=HTMLResponse)
    async def about_page(request: Request) -> HTMLResponse:
        session, fresh = session_for(request)
        locale = locale_for(request, session)
        attributions = [provider.attribution() for provider in app.state.providers.values()]
        response = render(
            "about.html",
            locale=locale,
            session=session,
            attributions=attributions,
        )
        if fresh:
            set_session(response, session)
        return response

    return app
