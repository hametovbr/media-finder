"""Processor-facing HTTP application."""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from media_finder_core.acquisition.persistence import SqlAlchemyAcquisitionQueries
from media_finder_core.catalog.persistence import SqlAlchemyCatalogQueries
from media_finder_core.exports import (
    EntityType,
    ExportRevisionSnapshot,
    ExportWarningPolicy,
    MetadataExportService,
    NamingExportService,
    NamingResult,
    NfoExportService,
)
from media_finder_core.platform import migration_state
from media_finder_sdk import NormalizedMetadata as SdkNormalizedMetadata
from media_finder_sdk import Provenance as SdkProvenance
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
bearer = HTTPBearer(auto_error=False)


class ProcessorModel(BaseModel):
    """Strict serialized value published by the processor API."""

    model_config = ConfigDict(extra="forbid")


class Provenance(SdkProvenance):
    """Stable processor wire provenance retained from API v1."""

    provider_id: str = Field(serialization_alias="provider_key")


class NormalizedMetadata(SdkNormalizedMetadata):
    """Processor API v1 projection of normalized module metadata."""

    provenance: Provenance


class ProcessorError(ProcessorModel):
    """Stable safe error details shared by every processor endpoint."""

    code: str
    request_id: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ProcessorErrorEnvelope(ProcessorModel):
    """Public processor error response envelope."""

    error: ProcessorError


class HealthStatus(ProcessorModel):
    """Liveness or readiness state."""

    status: Literal["live", "ready"]


PROCESSOR_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status_code: {
        "model": ProcessorErrorEnvelope,
        "description": description,
    }
    for status_code, description in {
        401: "A valid processor integration bearer token is required.",
        404: "The requested catalog or acquisition resource does not exist.",
        410: "The pinned metadata source has expired under its provider policy.",
        422: "The request selectors or parameters are invalid.",
        500: "The request could not be completed safely.",
    }.items()
}

NFO_RESPONSE_HEADERS: dict[str, dict[str, Any]] = {
    "Content-Disposition": {
        "description": "Safe attachment filename for the exported NFO document.",
        "schema": {"type": "string"},
    },
    "Warning": {
        "description": "Provider-owned metadata expiry warning when applicable.",
        "schema": {"type": "string"},
    },
    "Sunset": {
        "description": "Provider-owned metadata expiry time when applicable.",
        "schema": {"type": "string"},
    },
    "X-Media-Finder-Metadata-Expires": {
        "description": "Machine-readable metadata expiry time when applicable.",
        "schema": {"type": "string"},
    },
}

NFO_SUCCESS_RESPONSE: dict[str, Any] = {
    "description": "Jellyfin/Kodi-compatible NFO XML.",
    "headers": NFO_RESPONSE_HEADERS,
    "content": {"application/xml": {"schema": {"type": "string"}}},
}


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


class _CatalogExportReader:
    def __init__(self, queries: SqlAlchemyCatalogQueries) -> None:
        self._queries = queries

    def current_revision_id(self, media_item_id: str) -> str | None:
        item = self._queries.get_item(media_item_id)
        return item.current_revision_id if item is not None else None

    def revision(self, revision_id: str) -> ExportRevisionSnapshot | None:
        revision = self._queries.get_revision(revision_id)
        if revision is None:
            return None
        return ExportRevisionSnapshot(
            id=revision.id,
            effective=revision.effective,
            refresh_after=revision.refresh_after,
            expires_at=revision.expires_at,
            created_at=revision.created_at,
        )


class _AcquisitionExportReader:
    def __init__(self, queries: SqlAlchemyAcquisitionQueries) -> None:
        self._queries = queries

    def pinned_revision_id(self, acquisition_id: str) -> str | None:
        acquisition = self._queries.get(acquisition_id)
        return acquisition.metadata_revision_id if acquisition is not None else None


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


def create_processor_app(
    *,
    integration_token: str,
    clock: Callable[[], datetime] | None = None,
    retention_policies: Mapping[str, ExportWarningPolicy] | None = None,
    database_engine: Engine,
    sessions: sessionmaker[Session],
) -> FastAPI:
    """Create the processor adapter from root-owned runtime dependencies."""

    engine = database_engine
    integration_token_bytes = integration_token.encode()

    app = FastAPI(title="Media Finder processor API", version="1")
    app.state.engine = engine
    app.state.owns_engine = False
    app.state.sessions = sessions
    app.state.clock = clock or (lambda: datetime.now(UTC))
    session_source = sessions
    metadata_exports = MetadataExportService(
        catalog=_CatalogExportReader(SqlAlchemyCatalogQueries(session_source)),
        acquisitions=_AcquisitionExportReader(SqlAlchemyAcquisitionQueries(session_source)),
        retention_policies=dict(retention_policies or {}),
        clock=app.state.clock,
    )
    naming_exports = NamingExportService(metadata=metadata_exports)
    nfo_exports = NfoExportService(metadata=metadata_exports)

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

    @app.get("/health/live", response_model=HealthStatus)
    def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get(
        "/health/ready",
        response_model=HealthStatus,
        responses={
            503: {
                "model": ProcessorErrorEnvelope,
                "description": "The database or migration state is not ready.",
            }
        },
    )
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
        valid = hmac.compare_digest(supplied, integration_token_bytes)
        if credentials is None or credentials.scheme.casefold() != "bearer" or not valid:
            raise APIError(
                401,
                "authentication_required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    router = APIRouter(
        prefix="/api/v1",
        dependencies=[Depends(authenticate)],
        responses=PROCESSOR_ERROR_RESPONSES,
    )

    def export_failure(error: ValueError) -> APIError:
        code = str(error)
        if code == "metadata_source_expired":
            return APIError(410, code)
        if code in {
            "media_item_not_found",
            "metadata_revision_not_found",
            "acquisition_not_found",
        }:
            return APIError(404, code)
        if code == "metadata_snapshot_invalid":
            return APIError(500, code)
        if code == "export_warning_invalid":
            return APIError(500, "internal_error")
        return APIError(
            422,
            "request_validation_failed",
            details={"issues": [{"field": "selector", "type": code}]},
        )

    @router.get("/media-items/{item_id}/metadata", response_model=NormalizedMetadata)
    def media_item_metadata(item_id: str) -> dict[str, Any]:
        try:
            return metadata_exports.current(item_id).metadata.model_dump(mode="json")
        except ValueError as error:
            raise export_failure(error) from None

    @router.get("/acquisitions/{acquisition_id}/metadata", response_model=NormalizedMetadata)
    def acquisition_metadata(acquisition_id: str) -> dict[str, Any]:
        try:
            return metadata_exports.pinned(acquisition_id).metadata.model_dump(mode="json")
        except ValueError as error:
            raise export_failure(error) from None

    def naming_response(
        identity: str,
        pinned: bool,
        entity_type: Literal["movie", "tvshow", "season", "episode"],
        season_number: int | None,
        episode_numbers: list[int],
        target_extension: str | None,
        profile: str,
    ) -> dict[str, Any]:
        try:
            operation = naming_exports.pinned if pinned else naming_exports.current
            result = operation(
                identity,
                entity_type=EntityType(entity_type),
                season_number=season_number,
                episode_numbers=tuple(episode_numbers),
                target_extension=target_extension,
                profile=profile,
            )
        except ValueError as error:
            raise export_failure(error) from None
        return result.model_dump(mode="json")

    @router.get("/media-items/{item_id}/exports/naming", response_model=NamingResult)
    def media_item_naming(
        item_id: str,
        entity_type: Literal["movie", "tvshow", "season", "episode"],
        season_number: int | None = Query(default=None, ge=0),
        episode_numbers: Annotated[list[int] | None, Query()] = None,
        target_extension: str | None = None,
        profile: str = "jellyfin-v1",
    ) -> dict[str, Any]:
        return naming_response(
            item_id,
            False,
            entity_type,
            season_number,
            episode_numbers or [],
            target_extension,
            profile,
        )

    @router.get("/acquisitions/{acquisition_id}/exports/naming", response_model=NamingResult)
    def acquisition_naming(
        acquisition_id: str,
        entity_type: Literal["movie", "tvshow", "season", "episode"],
        season_number: int | None = Query(default=None, ge=0),
        episode_numbers: Annotated[list[int] | None, Query()] = None,
        target_extension: str | None = None,
        profile: str = "jellyfin-v1",
    ) -> dict[str, Any]:
        return naming_response(
            acquisition_id,
            True,
            entity_type,
            season_number,
            episode_numbers or [],
            target_extension,
            profile,
        )

    def nfo_response(
        identity: str,
        pinned: bool,
        entity_type: Literal["movie", "tvshow", "season", "episode"],
        season_number: int | None,
        episode_numbers: list[int],
    ) -> Response:
        try:
            operation = nfo_exports.pinned if pinned else nfo_exports.current
            result = operation(
                identity,
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
            raise export_failure(error) from None

        headers = {"Content-Disposition": content_disposition(result.filename)}
        if result.warning is not None:
            headers.update({header.name: header.value for header in result.warning.headers})
        return Response(content=result.xml, media_type="application/xml", headers=headers)

    def content_disposition(filename: str) -> str:
        try:
            filename.encode("ascii")
        except UnicodeEncodeError:
            encoded = quote(filename, safe="")
            return f"attachment; filename=\"metadata.nfo\"; filename*=UTF-8''{encoded}"
        return f'attachment; filename="{filename}"'

    @router.get(
        "/media-items/{item_id}/exports/nfo",
        response_class=Response,
        responses={200: NFO_SUCCESS_RESPONSE},
    )
    def media_item_nfo(
        item_id: str,
        entity_type: Literal["movie", "tvshow", "season", "episode"],
        season_number: int | None = Query(default=None, ge=0),
        episode_numbers: Annotated[list[int] | None, Query()] = None,
    ) -> Response:
        return nfo_response(item_id, False, entity_type, season_number, episode_numbers or [])

    @router.get(
        "/acquisitions/{acquisition_id}/exports/nfo",
        response_class=Response,
        responses={200: NFO_SUCCESS_RESPONSE},
    )
    def acquisition_nfo(
        acquisition_id: str,
        entity_type: Literal["movie", "tvshow", "season", "episode"],
        season_number: int | None = Query(default=None, ge=0),
        episode_numbers: Annotated[list[int] | None, Query()] = None,
    ) -> Response:
        return nfo_response(acquisition_id, True, entity_type, season_number, episode_numbers or [])

    app.include_router(router)
    return app


__all__ = [
    "APIError",
    "HealthStatus",
    "ProcessorError",
    "ProcessorErrorEnvelope",
    "create_processor_app",
]
