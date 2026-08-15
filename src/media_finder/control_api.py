"""Same-origin JSON adapter for the browser control gateway."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from media_finder_control import (
    BrowserSecurityPort,
    BrowserSession,
    ControlErrorEnvelope,
    ControlFailure,
    Locale,
    ManualDocumentV1,
    Page,
    PageRequest,
)
from media_finder_control.models import (
    AboutView,
    AcquisitionSubmissionRequest,
    AcquisitionView,
    CatalogItemView,
    CollectionChangeRequest,
    CollectionCreateRequest,
    CollectionView,
    DownloadDestination,
    EpisodeImportRequest,
    IntegrationDiagnostic,
    ManualImportRequest,
    ManualImportResult,
    MediaItemChangeRequest,
    MediaItemDetail,
    MediaItemOperation,
    MetadataProviderView,
    MetadataSearchRequest,
    MetadataSearchResult,
    MetadataSelectionRequest,
    ReleaseSearchRequest,
    ReleaseSearchResult,
    SessionUpdate,
    SessionView,
)
from media_finder_control.ports import ControlGateway
from pydantic import JsonValue
from starlette.exceptions import HTTPException as StarletteHTTPException

SESSION_COOKIE = "mf_session"
MAX_CONTROL_BODY_BYTES = 1024 * 1024


class ControlRequestBoundary:
    def __init__(self, security: BrowserSecurityPort) -> None:
        self.security = security

    async def mutation(self, request: Request) -> BrowserSession:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise ControlFailure(code="json_required", status=415)
        declared = request.headers.get("content-length")
        try:
            if declared is not None and int(declared) > MAX_CONTROL_BODY_BYTES:
                raise ControlFailure(code="request_body_too_large", status=413)
        except ValueError:
            raise ControlFailure(code="request_body_invalid", status=400) from None
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_CONTROL_BODY_BYTES:
                raise ControlFailure(code="request_body_too_large", status=413)
            chunks.append(chunk)
        request._body = b"".join(chunks)

        supplied_origin = request.headers.get("origin")
        effective_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if supplied_origin != effective_origin:
            raise ControlFailure(code="origin_invalid", status=403)
        session = await self.security.load_session(
            cookie=request.cookies.get(SESSION_COOKIE),
            accept_language=request.headers.get("accept-language"),
        )
        if session.is_new:
            raise ControlFailure(code="session_invalid", status=403)
        if not await self.security.validate_csrf(
            session=session,
            token=request.headers.get("x-csrf-token"),
        ):
            raise ControlFailure(code="csrf_invalid", status=403)
        request.state.control_session = session
        return session


def create_control_app(
    *,
    gateway: ControlGateway,
    security: BrowserSecurityPort,
    secure_cookie: bool = False,
) -> FastAPI:
    app = FastAPI(
        title="Media Finder browser control API",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
        responses={
            code: {"model": ControlErrorEnvelope}
            for code in (400, 403, 404, 405, 409, 410, 413, 415, 422, 503)
        },
    )
    boundary = ControlRequestBoundary(security)

    @app.middleware("http")
    async def request_identity(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = secrets.token_urlsafe(18)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ControlFailure)
    async def control_failure(request: Request, error: ControlFailure) -> JSONResponse:
        request_id = request.state.request_id
        body = error.error.model_copy(update={"request_id": request_id})
        return JSONResponse({"error": body.model_dump(mode="json")}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_failure(request: Request, error: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(value) for value in item["loc"]) for item in error.errors()]
        failure = ControlFailure(
            code="request_invalid",
            status=422,
            details={"fields": cast(JsonValue, fields)},
        )
        return await control_failure(request, failure)

    @app.exception_handler(StarletteHTTPException)
    async def framework_failure(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = "method_not_allowed" if error.status_code == 405 else "not_found"
        failure = ControlFailure(code=code, status=error.status_code)
        response = await control_failure(request, failure)
        if error.status_code == 405 and error.headers and "Allow" in error.headers:
            response.headers["Allow"] = error.headers["Allow"]
        return response

    @app.get("/v1/session", response_model=SessionView)
    async def session_resource(request: Request) -> JSONResponse:
        session = await security.load_session(
            cookie=request.cookies.get(SESSION_COOKIE),
            accept_language=request.headers.get("accept-language"),
        )
        encoded = await security.serialize_session(session=session)
        response = JSONResponse(SessionView.from_session(session).model_dump(mode="json"))
        response.set_cookie(
            SESSION_COOKIE,
            encoded,
            httponly=True,
            samesite="lax",
            secure=secure_cookie,
            path="/",
        )
        return response

    @app.patch(
        "/v1/session",
        response_model=SessionView,
        dependencies=[Depends(boundary.mutation)],
    )
    async def update_session(
        request: Request,
        update: SessionUpdate,
    ) -> JSONResponse:
        session: BrowserSession = request.state.control_session
        ui_locale = update.ui_locale or session.ui_locale
        explicit = session.metadata_locale_explicit
        metadata_locale = session.metadata_locale
        if update.metadata_locale is not None:
            metadata_locale = update.metadata_locale
            explicit = True
        elif update.ui_locale is not None and not explicit:
            metadata_locale = ui_locale
        changed = session.model_copy(
            update={
                "ui_locale": ui_locale,
                "metadata_locale": metadata_locale,
                "metadata_locale_explicit": explicit,
                "is_new": False,
            }
        )
        encoded = await security.serialize_session(session=changed)
        response = JSONResponse(SessionView.from_session(changed).model_dump(mode="json"))
        response.set_cookie(
            SESSION_COOKIE,
            encoded,
            httponly=True,
            samesite="lax",
            secure=secure_cookie,
            path="/",
        )
        return response

    @app.get("/v1/collections", response_model=Page[CollectionView])
    async def collections_resource(
        archived: bool = False,
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = None,
    ) -> Page[CollectionView]:
        return await gateway.list_collections(
            page=PageRequest(limit=limit, cursor=cursor),
            archived=archived,
        )

    @app.post(
        "/v1/collections",
        response_model=CollectionView,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(boundary.mutation)],
    )
    async def create_collection(request: CollectionCreateRequest) -> CollectionView:
        return await gateway.create_collection(name=request.name)

    @app.patch(
        "/v1/collections/{collection_id}",
        response_model=CollectionView,
        dependencies=[Depends(boundary.mutation)],
    )
    async def change_collection(
        collection_id: str, request: CollectionChangeRequest
    ) -> CollectionView:
        return await gateway.change_collection(
            collection_id=collection_id,
            archived=request.archived,
        )

    @app.get("/v1/media-items", response_model=Page[CatalogItemView])
    async def media_items_resource(
        locale: Locale = Locale.EN,
        archived: bool = False,
        collection_id: str | None = None,
        uncategorized: bool = False,
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = None,
    ) -> Page[CatalogItemView]:
        return await gateway.list_media_items(
            locale=locale,
            page=PageRequest(limit=limit, cursor=cursor),
            collection_id=collection_id,
            uncategorized=uncategorized,
            archived=archived,
        )

    @app.get("/v1/media-items/{item_id}", response_model=MediaItemDetail)
    async def media_item_resource(
        item_id: str,
        locale: Locale = Locale.EN,
    ) -> MediaItemDetail:
        return await gateway.get_media_item(item_id=item_id, locale=locale)

    @app.patch(
        "/v1/media-items/{item_id}",
        response_model=MediaItemDetail,
        dependencies=[Depends(boundary.mutation)],
    )
    async def change_media_item(
        item_id: str,
        request: MediaItemChangeRequest,
    ) -> MediaItemDetail:
        current = await gateway.get_media_item(item_id=item_id, locale=request.locale)
        collection_id = (
            request.collection_id
            if request.operation is MediaItemOperation.MOVE
            else current.collection_id
        )
        archived = {
            MediaItemOperation.MOVE: None,
            MediaItemOperation.ARCHIVE: True,
            MediaItemOperation.RESTORE: False,
        }[request.operation]
        return await gateway.change_media_item(
            item_id=item_id,
            collection_id=collection_id,
            archived=archived,
            locale=request.locale,
        )

    @app.get("/v1/metadata-providers", response_model=list[MetadataProviderView])
    async def metadata_providers_resource() -> tuple[MetadataProviderView, ...]:
        return await gateway.metadata_providers()

    @app.post(
        "/v1/metadata-searches",
        response_model=list[MetadataSearchResult],
        dependencies=[Depends(boundary.mutation)],
    )
    async def metadata_search_resource(
        search_request: MetadataSearchRequest,
    ) -> tuple[MetadataSearchResult, ...]:
        return await gateway.search_metadata(request=search_request)

    @app.post(
        "/v1/metadata-selections/{token}",
        response_model=MediaItemDetail,
        dependencies=[Depends(boundary.mutation)],
    )
    async def metadata_selection_resource(
        token: str,
        request: Request,
        selection: MetadataSelectionRequest,
    ) -> JSONResponse:
        session: BrowserSession = request.state.control_session
        result = await gateway.select_metadata(
            token=token,
            request=selection,
            locale=session.metadata_locale,
        )
        return JSONResponse(
            result.item.model_dump(mode="json"),
            status_code=201 if result.created else 200,
        )

    def manual_response(result: ManualImportResult) -> JSONResponse:
        if result.confirmation_token is not None:
            raise ControlFailure(
                code="confirmation_required",
                status=409,
                details={
                    "confirmation_token": result.confirmation_token,
                    "kind": "manual",
                },
            )
        if result.item is None:
            raise ControlFailure(code="manual_import_invalid", status=422)
        return JSONResponse(
            result.item.model_dump(mode="json"),
            status_code=201 if result.created else 200,
        )

    @app.post(
        "/v1/manual-imports",
        response_model=MediaItemDetail,
        dependencies=[Depends(boundary.mutation)],
    )
    async def manual_import_resource(import_request: ManualImportRequest) -> JSONResponse:
        return manual_response(await gateway.import_manual(request=import_request))

    @app.post(
        "/v1/manual-imports/{token}/confirm",
        response_model=MediaItemDetail,
        dependencies=[Depends(boundary.mutation)],
    )
    async def manual_confirmation_resource(token: str) -> JSONResponse:
        return manual_response(await gateway.confirm_manual(token=token))

    @app.put(
        "/v1/media-items/{item_id}/manual-metadata",
        response_model=MediaItemDetail,
        dependencies=[Depends(boundary.mutation)],
    )
    async def manual_edit_resource(
        item_id: str,
        document: ManualDocumentV1,
    ) -> JSONResponse:
        return manual_response(await gateway.edit_manual(item_id=item_id, document=document))

    @app.post(
        "/v1/media-items/{item_id}/episode-imports",
        response_model=MediaItemDetail,
        dependencies=[Depends(boundary.mutation)],
    )
    async def episode_import_resource(
        item_id: str,
        request: Request,
        episode_import: EpisodeImportRequest,
    ) -> MediaItemDetail:
        session: BrowserSession = request.state.control_session
        return await gateway.import_episodes(
            item_id=item_id,
            request=episode_import,
            locale=session.metadata_locale,
        )

    @app.post(
        "/v1/media-items/{item_id}/release-searches",
        response_model=list[ReleaseSearchResult],
        dependencies=[Depends(boundary.mutation)],
    )
    async def release_search_resource(
        item_id: str,
        search_request: ReleaseSearchRequest,
    ) -> tuple[ReleaseSearchResult, ...]:
        return await gateway.search_releases(item_id=item_id, request=search_request)

    @app.get("/v1/download-destinations", response_model=list[DownloadDestination])
    async def download_destinations_resource() -> tuple[DownloadDestination, ...]:
        return await gateway.list_destinations()

    @app.post(
        "/v1/acquisitions",
        response_model=AcquisitionView,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(boundary.mutation)],
    )
    async def acquisition_submission_resource(
        submission: AcquisitionSubmissionRequest,
    ) -> AcquisitionView:
        return await gateway.submit_acquisition(request=submission)

    @app.post(
        "/v1/acquisitions/{acquisition_id}/reconcile",
        response_model=AcquisitionView,
        dependencies=[Depends(boundary.mutation)],
    )
    async def acquisition_reconcile_resource(acquisition_id: str) -> AcquisitionView:
        return await gateway.reconcile_acquisition(acquisition_id=acquisition_id)

    @app.get("/v1/integrations", response_model=list[IntegrationDiagnostic])
    async def integrations_resource() -> tuple[IntegrationDiagnostic, ...]:
        return await gateway.integration_diagnostics()

    @app.get("/v1/about", response_model=AboutView)
    async def about_resource() -> AboutView:
        return await gateway.about()

    app.state.gateway = gateway
    app.state.security = security
    return app
