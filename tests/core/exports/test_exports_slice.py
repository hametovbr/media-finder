"""Focused framework-free contract for metadata, naming, and NFO exports."""

from __future__ import annotations

import ast
import importlib
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
from media_finder_sdk import (
    Artwork,
    Episode,
    ExportHeader,
    ExportWarning,
    MediaKind,
    NormalizedMetadata,
    Person,
    Provenance,
    Rating,
    RetentionPolicy,
    Season,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).parents[3]
EXPORTS_ROOT = ROOT / "packages" / "core" / "src" / "media_finder_core" / "exports"


def _api() -> SimpleNamespace:
    try:
        modules = {
            name: importlib.import_module(f"media_finder_core.exports.{name}")
            for name in ("ports", "metadata", "naming", "nfo")
        }
    except ModuleNotFoundError as error:
        pytest.fail(f"exports bounded context is missing: {error.name}")
    required = {
        "CatalogExportReadPort": getattr(modules["ports"], "CatalogExportReadPort", None),
        "AcquisitionExportReadPort": getattr(modules["ports"], "AcquisitionExportReadPort", None),
        "ExportRevisionSnapshot": getattr(modules["metadata"], "ExportRevisionSnapshot", None),
        "ResolvedMetadata": getattr(modules["metadata"], "ResolvedMetadata", None),
        "MetadataExportService": getattr(modules["metadata"], "MetadataExportService", None),
        "EntityType": getattr(modules["naming"], "EntityType", None),
        "NamingResult": getattr(modules["naming"], "NamingResult", None),
        "NamingExportService": getattr(modules["naming"], "NamingExportService", None),
        "render_naming": getattr(modules["naming"], "render_naming", None),
        "NfoResult": getattr(modules["nfo"], "NfoResult", None),
        "NfoExportService": getattr(modules["nfo"], "NfoExportService", None),
        "render_nfo": getattr(modules["nfo"], "render_nfo", None),
    }
    missing = sorted(name for name, value in required.items() if value is None)
    assert missing == [], f"exports public application types are missing: {missing}"
    return SimpleNamespace(**required, **modules)


def _movie(*, title: str, provider_id: str = "provider-a") -> NormalizedMetadata:
    return NormalizedMetadata(
        kind=MediaKind.MOVIE,
        titles={"en": title},
        original_title="Original title",
        year=2001,
        plot="A journey <beyond> & home.",
        release_date=date(2001, 7, 20),
        runtime_minutes=125,
        provider_ids={provider_id: "movie-1"},
        ratings=(Rating(source="critic", value=8.5, votes=42),),
        genres=("Animation",),
        tags=("coming-of-age",),
        countries=("Japan",),
        studios=("Studio Ghibli",),
        people=(
            Person(name="Director Name", role="director"),
            Person(name="Actor Name", role="actor", character="Hero"),
        ),
        artwork=(
            Artwork(
                kind="poster",
                url="https://images.example.test/poster.jpg",
                language="en",
            ),
        ),
        provenance=Provenance(
            provider_id=provider_id,
            external_id="movie-1",
            locale="en",
            fetched_at=NOW,
        ),
        completeness=0.95,
        structural_quality=1,
    )


def _series(*, provider_id: str = "provider-a") -> NormalizedMetadata:
    return NormalizedMetadata(
        kind=MediaKind.SERIES,
        titles={"ru": "Волшебный сериал"},
        year=2024,
        provider_ids={provider_id: "series-1"},
        seasons=(
            Season(
                number=0,
                title="Specials",
                episodes=(
                    Episode(
                        number=1,
                        title="Special & One",
                        ordering=7,
                        provider_ids={provider_id: "special-1"},
                    ),
                ),
            ),
            Season(
                number=1,
                title="Season 1",
                episodes=(
                    Episode(number=1, title="Первая серия"),
                    Episode(number=2, title="Вторая серия"),
                    Episode(number=3, title="Третья серия"),
                ),
            ),
        ),
        provenance=Provenance(
            provider_id=provider_id,
            external_id="series-1",
            locale="ru",
            fetched_at=NOW,
        ),
    )


class _CatalogExports:
    def __init__(self) -> None:
        self.current: dict[str, str] = {}
        self.revisions: dict[str, object] = {}
        self.current_calls: list[str] = []
        self.revision_calls: list[str] = []

    def current_revision_id(self, media_item_id: str) -> str | None:
        self.current_calls.append(media_item_id)
        return self.current.get(media_item_id)

    def revision(self, revision_id: str):
        self.revision_calls.append(revision_id)
        return self.revisions.get(revision_id)


class _AcquisitionExports:
    def __init__(self) -> None:
        self.pinned: dict[str, str] = {}
        self.calls: list[str] = []

    def pinned_revision_id(self, acquisition_id: str) -> str | None:
        self.calls.append(acquisition_id)
        return self.pinned.get(acquisition_id)


class _WarningPolicy:
    def __init__(self) -> None:
        self.seen: list[RetentionPolicy] = []
        self.warning = ExportWarning(
            headers=(
                ExportHeader(name="Warning", value='299 Media Finder "Metadata expires"'),
                ExportHeader(name="Sunset", value="Mon, 01 Sep 2026 12:00:00 GMT"),
                ExportHeader(
                    name="X-Media-Finder-Metadata-Expires",
                    value="2026-09-01T12:00:00+00:00",
                ),
            )
        )

    def retention_for(self, created_at: datetime) -> RetentionPolicy:
        del created_at
        return RetentionPolicy()

    def plan(self, subject: object, now: datetime):
        raise AssertionError((subject, now))

    def export_warning(self, policy: RetentionPolicy, now: datetime) -> ExportWarning:
        assert now == NOW
        self.seen.append(policy)
        return self.warning

    def close(self) -> None: ...


def _revision(
    api: SimpleNamespace,
    revision_id: str,
    metadata: NormalizedMetadata | None,
    *,
    expires_at: datetime | None = None,
):
    return api.ExportRevisionSnapshot(
        id=revision_id,
        effective=metadata,
        refresh_after=None,
        expires_at=expires_at,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _services() -> SimpleNamespace:
    api = _api()
    catalog = _CatalogExports()
    acquisitions = _AcquisitionExports()
    warning = _WarningPolicy()
    metadata = api.MetadataExportService(
        catalog=catalog,
        acquisitions=acquisitions,
        retention_policies={"provider-a": warning},
        clock=lambda: NOW,
    )
    return SimpleNamespace(
        api=api,
        catalog=catalog,
        acquisitions=acquisitions,
        warning=warning,
        metadata=metadata,
        naming=api.NamingExportService(metadata=metadata),
        nfo=api.NfoExportService(metadata=metadata),
    )


def test_current_and_pinned_metadata_use_only_scalar_ports_and_immutable_effective_values() -> None:
    context = _services()
    context.catalog.current["item-1"] = "revision-current"
    context.acquisitions.pinned["acquisition-1"] = "revision-pinned"
    context.catalog.revisions.update(
        {
            "revision-current": _revision(
                context.api, "revision-current", _movie(title="Current title")
            ),
            "revision-pinned": _revision(
                context.api, "revision-pinned", _movie(title="Pinned title")
            ),
        }
    )

    current = context.metadata.current("item-1")
    pinned = context.metadata.pinned("acquisition-1")

    assert current.metadata.titles["en"] == "Current title"
    assert pinned.metadata.titles["en"] == "Pinned title"
    assert context.catalog.current_calls == ["item-1"]
    assert context.acquisitions.calls == ["acquisition-1"]
    assert context.catalog.revision_calls == ["revision-current", "revision-pinned"]
    assert {field.name for field in fields(context.api.ExportRevisionSnapshot)} == {
        "id",
        "effective",
        "refresh_after",
        "expires_at",
        "created_at",
    }
    with pytest.raises((FrozenInstanceError, AttributeError)):
        pinned.revision_id = "other"
    with pytest.raises(TypeError):
        pinned.metadata.titles["en"] = "mutated"


@pytest.mark.parametrize("purged", [False, True])
def test_expiry_blocks_metadata_naming_and_nfo_before_or_after_physical_purge(
    purged: bool,
) -> None:
    context = _services()
    context.catalog.current["item-expired"] = "revision-expired"
    context.acquisitions.pinned["acquisition-expired"] = "revision-expired"
    context.catalog.revisions["revision-expired"] = _revision(
        context.api,
        "revision-expired",
        None if purged else _movie(title="Must not escape"),
        expires_at=NOW,
    )

    operations = (
        lambda: context.metadata.current("item-expired"),
        lambda: context.metadata.pinned("acquisition-expired"),
        lambda: context.naming.current("item-expired", entity_type=context.api.EntityType.MOVIE),
        lambda: context.naming.pinned(
            "acquisition-expired", entity_type=context.api.EntityType.MOVIE
        ),
        lambda: context.nfo.current("item-expired", entity_type=context.api.EntityType.MOVIE),
        lambda: context.nfo.pinned("acquisition-expired", entity_type=context.api.EntityType.MOVIE),
    )
    for operation in operations:
        with pytest.raises(ValueError, match="metadata_source_expired"):
            operation()


def test_nfo_export_carries_defensively_validated_provider_warning() -> None:
    context = _services()
    expires_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    context.catalog.current["item-warning"] = "revision-warning"
    context.catalog.revisions["revision-warning"] = _revision(
        context.api,
        "revision-warning",
        _movie(title="Warning movie"),
        expires_at=expires_at,
    )

    exported = context.nfo.current("item-warning", entity_type=context.api.EntityType.MOVIE)

    assert exported.warning == context.warning.warning
    assert context.warning.seen == [RetentionPolicy(refresh_after=None, expires_at=expires_at)]
    assert "Warning movie" in exported.xml

    forged = ExportHeader.model_construct(name="Set-Cookie", value="unsafe=session")
    context.warning.warning = ExportWarning.model_construct(headers=(forged,))
    with pytest.raises(ValueError, match="export_warning_invalid"):
        context.nfo.current("item-warning", entity_type=context.api.EntityType.MOVIE)


def test_naming_is_extension_independent_portable_and_supports_specials_and_ranges() -> None:
    api = _api()
    metadata = _series()
    extensionless = api.render_naming(
        metadata,
        entity_type=api.EntityType.EPISODE,
        season_number=1,
        episode_numbers=(1, 2),
    )
    special = api.render_naming(
        metadata,
        entity_type=api.EntityType.EPISODE,
        season_number=0,
        episode_numbers=(1,),
        target_extension="WEBM",
    )

    assert extensionless.relative_directory == "Волшебный сериал (2024)/Season 01"
    assert extensionless.basename == "Волшебный сериал - S01E01-E02"
    assert extensionless.target_extension is None
    assert not extensionless.relative_path.endswith((".mkv", ".mp4", ".webm"))
    assert special.target_extension == "webm"
    assert "Season 00" in special.relative_directory
    assert "S00E01 - Special & One" in special.basename

    for extension in ("mkv", "mp4", "webm"):
        rendered = api.render_naming(
            metadata,
            entity_type=api.EntityType.EPISODE,
            season_number=1,
            episode_numbers=(1, 2),
            target_extension=extension,
        )
        assert rendered.basename == extensionless.basename
        assert rendered.relative_path == f"{extensionless.relative_path}.{extension}"


def test_naming_rejects_non_contiguous_selection_and_sanitizes_reserved_paths() -> None:
    api = _api()
    with pytest.raises(ValueError, match="naming_selector_invalid"):
        api.render_naming(
            _series(),
            entity_type=api.EntityType.EPISODE,
            season_number=1,
            episode_numbers=(1, 3),
        )

    unsafe = _movie(title="CON")
    rendered = api.render_naming(unsafe, entity_type=api.EntityType.MOVIE)
    assert rendered.relative_directory == "_CON (2001)"
    assert ".." not in rendered.relative_path
    assert not any(character in rendered.relative_path for character in '<>:"|?*\\')


def test_nfo_is_rich_xml_special_aware_and_never_contains_raw_or_user_state() -> None:
    api = _api()
    movie = api.render_nfo(_movie(title="A Movie & Home"), entity_type=api.EntityType.MOVIE)
    special = api.render_nfo(
        _series(),
        entity_type=api.EntityType.EPISODE,
        season_number=0,
        episode_numbers=(1,),
    )

    movie_root = ElementTree.fromstring(movie.xml)
    special_root = ElementTree.fromstring(special.xml)
    assert movie_root.tag == "movie"
    assert movie_root.findtext("title") == "A Movie & Home"
    assert movie_root.findtext("originaltitle") == "Original title"
    assert movie_root.findtext("runtime") == "125"
    assert movie_root.findtext("genre") == "Animation"
    assert movie_root.findtext("director") == "Director Name"
    assert movie_root.find("ratings/rating/value").text == "8.5"
    assert special_root.tag == "episodedetails"
    assert special_root.findtext("season") == "0"
    assert special_root.findtext("episode") == "1"
    assert special_root.findtext("displayepisode") == "7"
    combined = f"{movie.xml}{special.xml}".casefold()
    assert all(
        forbidden not in combined for forbidden in ("raw_payload", "playcount", "watched", "resume")
    )


def test_multi_episode_naming_is_allowed_while_nfo_is_rejected() -> None:
    api = _api()
    naming = api.render_naming(
        _series(),
        entity_type=api.EntityType.EPISODE,
        season_number=1,
        episode_numbers=(1, 2),
    )
    assert "S01E01-E02" in naming.basename
    with pytest.raises(ValueError, match="nfo_multi_episode_unsupported"):
        api.render_nfo(
            _series(),
            entity_type=api.EntityType.EPISODE,
            season_number=1,
            episode_numbers=(1, 2),
        )


def test_exports_ports_are_explicit_and_boundary_has_no_framework_or_raw_payload_imports() -> None:
    api = _api()
    assert getattr(api.CatalogExportReadPort, "_is_protocol", False) is True
    assert getattr(api.AcquisitionExportReadPort, "_is_protocol", False) is True

    forbidden_prefixes = (
        "sqlalchemy",
        "fastapi",
        "media_finder_server",
        "media_finder_metadata_",
        "media_finder_release_",
        "media_finder_download_",
    )
    violations: list[str] = []
    for name in ("ports.py", "metadata.py", "naming.py", "nfo.py"):
        path = EXPORTS_ROOT / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                modules = []
            violations.extend(
                f"{name}:{node.lineno}:{module}"
                for module in modules
                if module.startswith(forbidden_prefixes)
                or module.endswith(".persistence")
                or module
                in {
                    "media_finder_core.catalog.models",
                    "media_finder_core.acquisition.models",
                }
            )
            if isinstance(node, ast.Name) and node.id in {
                "ProviderPayload",
                "raw_payload",
                "Session",
            }:
                violations.append(f"{name}:{node.lineno}:{node.id}")
            if isinstance(node, ast.Attribute) and node.attr == "raw_payload":
                violations.append(f"{name}:{node.lineno}:raw_payload")
    assert violations == []
