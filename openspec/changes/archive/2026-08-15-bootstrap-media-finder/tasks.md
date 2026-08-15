## 1. Python and persistence foundation

- [x] 1.1 Create the Python 3.13 `uv` project, local asset build, formatting, linting, typing, and test configuration.
- [x] 1.2 Add application configuration with environment-only secret resolution and safe redaction.
- [x] 1.3 Add SQLAlchemy models and Alembic migrations for collections, media items, immutable metadata revisions, acquisitions, download-client instances, and settings.
- [x] 1.4 Configure SQLite WAL, foreign keys, uniqueness, archive semantics, and migration-aware readiness.
- [x] 1.5 Add deterministic tests for provider identity, Manual UUIDv4 allocation/import preservation, duplicate warnings, archive behavior, immutable revisions, and idempotency constraints.

## 2. Module SDK and metadata providers

- [x] 2.1 Define versioned public manifests, Pydantic types, standardized errors, and metadata-provider/download-client protocols.
- [x] 2.2 Build fixture-driven conformance suites proving modules require no database or UI-template access.
- [x] 2.3 Build generic module settings forms from typed schemas and environment references without module HTML or JavaScript.
- [x] 2.4 Implement Manual movie/series editing, schema-v1 JSON import, and atomic episode CSV import with immutable revisions.
- [x] 2.5 Implement TMDB search, fetch, normalization, attribution, provenance, and locale behavior.
- [x] 2.6 Implement provider-owned retention hooks, generic startup/daily maintenance, fake-clock refresh/purge tests, and core checks that exclude provider-specific policy.

## 3. Torrent acquisition

- [x] 3.1 Implement the Prowlarr torrent-only adapter, filters, safe normalized results, and bounded in-memory opaque-token cache.
- [x] 3.2 Implement safe GUID/infohash validation plus source-page origin/path sanitization and tests proving uncertain identifiers, secret path segments, artifacts, credentials, queries, fragments, and passkeys never reach persistence or logs.
- [x] 3.3 Implement named download-client instances and live destination validation.
- [x] 3.4 Implement the qBittorrent module for magnet and in-memory torrent submission, category mapping, exact tags, and correlation lookup.
- [x] 3.5 Implement transactional pending Acquisition creation, pinned revisions, idempotent submission, submitted/failed outcomes, and timeout lookup.
- [x] 3.6 Implement explicit manual pending reconciliation and restart tests that prove no automatic resubmission.

## 4. Processor-facing APIs

- [x] 4.1 Add unauthenticated liveness/readiness and Bearer-protected `/api/v1` routing with constant-time token checks.
- [x] 4.2 Add request IDs, stable machine error envelopes, safe validation details, and structured-log redaction.
- [x] 4.3 Add current media-item and pinned Acquisition metadata endpoints without raw provider payloads.
- [x] 4.4 Implement `jellyfin-v1` path sanitation and naming for movies, episodes, specials, multi-episode ranges, Unicode, reserved names, and optional extensions.
- [x] 4.5 Implement structured movie, TV show, season, and single-episode NFO XML plus multi-episode rejection.
- [x] 4.6 Implement provider-expiry 410 responses and TMDB module warning headers without provenance sidecar output.

## 5. Bilingual server-rendered UI

- [x] 5.1 Establish Jinja2/HTMX layouts, local assets, poster grid, responsive collection sidebar, Archive, Settings, and About/Credits.
- [x] 5.2 Add English and Russian gettext catalogs, locale detection, cookie override, and independent metadata locale selection.
- [x] 5.3 Add metadata search/Manual entry, confirmation, duplicate handling, item save, and optional release-search flow.
- [x] 5.4 Add media Overview, Seasons/Episodes, and Acquisitions views with bounded status presentation.
- [x] 5.5 Add Prowlarr result selection, client/destination reload, idempotent submit, and manual reconciliation views.
- [x] 5.6 Add first-run readiness that permits Manual-only use and TMDB official attribution.
- [x] 5.7 Add signed sessions, CSRF enforcement, configurable secure cookies, invariant machine-code to localized-message mapping, pending-card semantics, semantic feedback, and keyboard-accessible RU/EN Playwright tests.

## 6. Container and automation

- [x] 6.1 Add a non-root multi-stage production image and migration-before-server entrypoint with one Uvicorn worker.
- [x] 6.2 Add an infrastructure-neutral Compose example with localhost port, `/data`, healthcheck, and no media/download mounts.
- [x] 6.3 Add documentation-policy, OpenSpec, format, lint, type, unit, integration, contract, browser, and production-image GitHub Actions checks.
- [x] 6.4 Add amd64/arm64 GHCR release automation for immutable version, moving minor, stable latest, and main-branch edge tags.
- [x] 6.5 Document configuration, external authentication, backup/upgrade/rollback, reverse-proxy, volume, port, and network customization.

## 7. Release readiness

- [x] 7.1 Run the complete pristine validation matrix and independent security, module-boundary, and architecture reviews.
- [x] 7.2 Resolve all blocking findings and verify acceptance scenarios in both supported locales.
- [x] 7.3 Synchronize the approved capability specs, archive `bootstrap-media-finder`, and verify strict validation.
- [x] 7.4 Create the first stable GitHub Release only after required checks pass and `/data` upgrade guidance is published.
