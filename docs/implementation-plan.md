# Media Finder MVP Implementation Plan

## Global Constraints

- Repository documentation and developer-facing prose are English-only. Russian is limited to localization catalogs, localization tests, and user metadata fixtures.
- OpenSpec is the source of truth for product behavior, UX, architecture, APIs, schemas, and module contracts.
- The service is a catalog and acquisition control plane. It does not scan, mux, move, or monitor media files and does not invoke Jellyfin.
- Metadata retention belongs to provider modules. Core contains only a provider-agnostic maintenance runner.
- Media naming is container-format independent; MKV is never assumed.
- Integration configuration enters through exact module-declared environment variables. Neither resolved values nor environment-variable references are persisted, returned, or logged.
- Production behavior is developed test-first. Each completed task is independently reviewed, committed, and pushed.

## Task 1: Spec-first repository bootstrap

Create the pinned OpenSpec toolchain and lock file, initialize the Codex core workflow skills, author the active `bootstrap-media-finder` change, add the short root `AGENTS.md`, MIT license, minimal contributor/security/readme documentation, three validated project skills, and an interactive low-fidelity wireframe design artifact. Validate the OpenSpec change and all project skills. This task must contain no application code.

## Task 2: Domain, persistence, and metadata modules

Implement the Python project foundation, SQLAlchemy/Alembic SQLite storage, immutable domain revisions, collections and archive semantics, provider and download-client protocols, generic module configuration, Manual metadata, TMDB metadata, and provider-owned retention. Use TDD and include conformance tests proving that modules need no database or template access.

## Task 3: Acquisition submission

Implement the Prowlarr torrent-only adapter, memory-only opaque result cache, qBittorrent module, sanitized acquisition snapshots, idempotent submission, exact correlation tokens, timeout lookup, and manual pending reconciliation. Use fakes for deterministic integration tests and keep artifact secrets out of persistence and logs.

## Task 4: Public metadata, naming, and NFO APIs

Implement Bearer-protected metadata and export endpoints, public health endpoints, stable request-ID error envelopes, the `jellyfin-v1` extension-independent naming profile, and Jellyfin/Kodi-compatible XML exports. Cover expiry, specials, Unicode, reserved names, multiple extensions, and multi-episode NFO rejection with tests.

## Task 5: Bilingual bundled browser UI

Implement the responsive, separately buildable React/Vite interface over
`/api/control/v1` for catalog and read-only collection browsing, media details,
provider metadata selection, Manual structured create and lossless edit,
complete Manual JSON import, atomic episode CSV import, release search, and
Acquisition submission. Preserve RU/EN localization, locale selection, signed
sessions, CSRF, keyboard accessibility, and deterministic isolated browser
fixtures. Settings, diagnostics, About/Credits, collection mutation,
Acquisition history, and reconciliation are intentionally outside the bundled
interface.

## Task 6: Container, CI, release, and operator documentation

Implement the non-root production image, generic Compose example, migrations-before-start entrypoint, healthcheck, backup/upgrade and reverse-proxy guidance, GitHub Actions validation, multi-architecture GHCR publishing, SemVer tag policy, and repository templates. Keep the example independent of private infrastructure and media mounts.

## Task 7: Whole-branch validation and release readiness

Run an independent whole-branch review, resolve all blocking findings, execute the full pristine verification matrix, synchronize and archive the OpenSpec change, and prepare the feature branch for integration without changing `main` directly.
