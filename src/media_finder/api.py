"""Processor-facing HTTP application."""

from __future__ import annotations

import hmac
import re
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import EnvReference, resolve_env_reference
from .db import create_database, migration_state, session_factory
from .models import Acquisition, MediaItem, MetadataRevision
from .naming import EntityType, render_naming
from .nfo import render_nfo
from .sdk.protocols import MetadataProvider
from .sdk.types import ExportWarning, NormalizedMetadata, RetentionPolicy

REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
bearer = HTTPBearer(auto_error=False)


class APIError(Exception):
    """A language-neutral, safe error intended for public serialization."""

    def __init__(
        self,
        status_code: int,
        code: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.details = details or {}
        self.headers = headers or {}


def _error_response(request: Request, error: APIError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid4()))
    headers = {"X-Request-ID": request_id, **error.headers}
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "request_id": request_id,
                "details": error.details,
            }
        },
        headers=headers,
    )


def create_app(
    database_url: str,
    *,
    integration_token_reference: str,
    clock: Callable[[], datetime] | None = None,
    providers: Mapping[str, MetadataProvider] | None = None,
    database_engine: Engine | None = None,
    sessions: sessionmaker[Session] | None = None,
) -> FastAPI:
    """Create the HTTP application with explicit runtime dependencies."""

    owns_engine = database_engine is None
    engine = database_engine or create_database(database_url)
    reference = EnvReference(value=integration_token_reference)
    integration_token = resolve_env_reference(reference).get_secret_value().encode()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owns_engine:
                engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.state.engine = engine
    app.state.owns_engine = owns_engine
    app.state.clock = clock or (lambda: datetime.now(UTC))
    app.state.providers = dict(providers or {})
    session_source = sessions or session_factory(engine)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Any) -> Any:
        supplied = request.headers.get("X-Request-ID", "")
        request.state.request_id = supplied if REQUEST_ID.fullmatch(supplied) else str(uuid4())
        try:
            response = await call_next(request)
        except APIError as error:
            return _error_response(request, error)
        except Exception:
            return _error_response(request, APIError(500, "internal_error"))
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, error: APIError) -> JSONResponse:
        return _error_response(request, error)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        issues = [
            {
                "field": ".".join(str(part) for part in issue["loc"] if part != "query"),
                "type": issue["type"],
            }
            for issue in error.errors()
        ]
        return _error_response(
            request,
            APIError(422, "request_validation_failed", details={"issues": issues}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def framework_http_error_handler(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        codes = {
            400: "bad_request",
            401: "authentication_required",
            403: "forbidden",
            404: "route_not_found",
            405: "method_not_allowed",
            413: "request_too_large",
            415: "unsupported_media_type",
            429: "rate_limit_exceeded",
        }
        code = codes.get(
            error.status_code, "http_error" if error.status_code < 500 else "internal_error"
        )
        response_headers: dict[str, str] = {}
        if error.status_code == 405 and error.headers and "Allow" in error.headers:
            response_headers["Allow"] = error.headers["Allow"]
        return _error_response(
            request,
            APIError(error.status_code, code, headers=response_headers),
        )

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    def ready() -> dict[str, str]:
        try:
            state = migration_state(engine)
        except Exception:
            raise APIError(503, "database_not_ready") from None
        if not state.ready:
            raise APIError(503, "database_not_ready")
        return {"status": "ready"}

    def authenticate(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        supplied = credentials.credentials.encode() if credentials is not None else b""
        valid = hmac.compare_digest(supplied, integration_token)
        if credentials is None or credentials.scheme.casefold() != "bearer" or not valid:
            raise APIError(
                401,
                "authentication_required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])

    def validated_snapshot(revision: MetadataRevision) -> NormalizedMetadata:
        expires_at = revision.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        now = app.state.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        if revision.effective_payload is None or (expires_at is not None and now >= expires_at):
            raise APIError(410, "metadata_source_expired")
        try:
            return NormalizedMetadata.model_validate(revision.effective_payload)
        except Exception:
            raise APIError(500, "metadata_snapshot_invalid") from None

    def revision_snapshot(revision: MetadataRevision) -> dict[str, Any]:
        return validated_snapshot(revision).model_dump(mode="json")

    def current_revision(item_id: str) -> MetadataRevision:
        with session_source() as session:
            item = session.get(MediaItem, item_id)
            if item is None or item.current_revision_id is None:
                raise APIError(404, "media_item_not_found")
            revision = session.get(MetadataRevision, item.current_revision_id)
            if revision is None:
                raise APIError(404, "metadata_revision_not_found")
            session.expunge(revision)
            return revision

    def pinned_revision(acquisition_id: str) -> MetadataRevision:
        try:
            identity = UUID(acquisition_id)
        except ValueError:
            raise APIError(404, "acquisition_not_found") from None
        with session_source() as session:
            acquisition = session.get(Acquisition, identity)
            if acquisition is None:
                raise APIError(404, "acquisition_not_found")
            revision = session.get(MetadataRevision, acquisition.metadata_revision_id)
            if revision is None:
                raise APIError(404, "metadata_revision_not_found")
            session.expunge(revision)
            return revision

    @router.get("/media-items/{item_id}/metadata")
    def media_item_metadata(item_id: str) -> dict[str, Any]:
        return revision_snapshot(current_revision(item_id))

    @router.get("/acquisitions/{acquisition_id}/metadata")
    def acquisition_metadata(acquisition_id: str) -> dict[str, Any]:
        return revision_snapshot(pinned_revision(acquisition_id))

    def naming_response(
        revision: MetadataRevision,
        entity_type: Literal["movie", "tvshow", "season", "episode"],
        season_number: int | None,
        episode_numbers: list[int],
        target_extension: str | None,
        profile: str,
    ) -> dict[str, Any]:
        try:
            result = render_naming(
                validated_snapshot(revision),
                entity_type=EntityType(entity_type),
                season_number=season_number,
                episode_numbers=tuple(episode_numbers),
                target_extension=target_extension,
                profile=profile,
            )
        except ValueError as error:
            raise APIError(
                422,
                "request_validation_failed",
                details={"issues": [{"field": "selector", "type": str(error)}]},
            ) from None
        return result.model_dump(mode="json")

    @router.get("/media-items/{item_id}/exports/naming")
    def media_item_naming(
        item_id: str,
        entity_type: Literal["movie", "tvshow", "season", "episode"],
        season_number: int | None = Query(default=None, ge=0),
        episode_numbers: Annotated[list[int] | None, Query()] = None,
        target_extension: str | None = None,
        profile: str = "jellyfin-v1",
    ) -> dict[str, Any]:
        return naming_response(
            current_revision(item_id),
            entity_type,
            season_number,
            episode_numbers or [],
            target_extension,
            profile,
        )

    @router.get("/acquisitions/{acquisition_id}/exports/naming")
    def acquisition_naming(
        acquisition_id: str,
        entity_type: Literal["movie", "tvshow", "season", "episode"],
        season_number: int | None = Query(default=None, ge=0),
        episode_numbers: Annotated[list[int] | None, Query()] = None,
        target_extension: str | None = None,
        profile: str = "jellyfin-v1",
    ) -> dict[str, Any]:
        return naming_response(
            pinned_revision(acquisition_id),
            entity_type,
            season_number,
            episode_numbers or [],
            target_extension,
            profile,
        )

    def nfo_response(
        revision: MetadataRevision,
        entity_type: Literal["movie", "tvshow", "season", "episode"],
        season_number: int | None,
        episode_numbers: list[int],
    ) -> Response:
        try:
            result = render_nfo(
                validated_snapshot(revision),
                entity_type=EntityType(entity_type),
                season_number=season_number,
                episode_numbers=tuple(episode_numbers),
            )
        except ValueError as error:
            if str(error) == "nfo_multi_episode_unsupported":
                raise APIError(
                    422,
                    "nfo_multi_episode_unsupported",
                    details={"recommendation": "split_episodes"},
                ) from None
            raise APIError(
                422,
                "request_validation_failed",
                details={"issues": [{"field": "selector", "type": str(error)}]},
            ) from None

        headers = {"Content-Disposition": content_disposition(result.filename)}
        provider = app.state.providers.get(revision.provider_key)
        if provider is not None:
            warning = provider.export_warning(
                RetentionPolicy(
                    refresh_after=revision.refresh_after,
                    expires_at=revision.expires_at,
                ),
                app.state.clock(),
            )
            if warning is not None:
                validated_warning = ExportWarning.model_validate(warning.model_dump())
                headers.update(validated_warning.as_headers())
        return Response(content=result.xml, media_type="application/xml", headers=headers)

    def content_disposition(filename: str) -> str:
        try:
            filename.encode("ascii")
        except UnicodeEncodeError:
            encoded = quote(filename, safe="")
            return f"attachment; filename=\"metadata.nfo\"; filename*=UTF-8''{encoded}"
        return f'attachment; filename="{filename}"'

    @router.get("/media-items/{item_id}/exports/nfo")
    def media_item_nfo(
        item_id: str,
        entity_type: Literal["movie", "tvshow", "season", "episode"],
        season_number: int | None = Query(default=None, ge=0),
        episode_numbers: Annotated[list[int] | None, Query()] = None,
    ) -> Response:
        return nfo_response(
            current_revision(item_id), entity_type, season_number, episode_numbers or []
        )

    @router.get("/acquisitions/{acquisition_id}/exports/nfo")
    def acquisition_nfo(
        acquisition_id: str,
        entity_type: Literal["movie", "tvshow", "season", "episode"],
        season_number: int | None = Query(default=None, ge=0),
        episode_numbers: Annotated[list[int] | None, Query()] = None,
    ) -> Response:
        return nfo_response(
            pinned_revision(acquisition_id), entity_type, season_number, episode_numbers or []
        )

    app.include_router(router)
    return app
