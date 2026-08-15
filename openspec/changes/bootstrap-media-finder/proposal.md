## Why

Self-hosted media users need a small catalog and acquisition control plane that preserves chosen metadata, delegates downloads, and gives external processors stable naming and NFO contracts without inheriting the file-management scope and provider assumptions of existing media managers. Establishing the behavior and extension contracts before implementation keeps the MVP auditable, interoperable, and practical to operate.

## What Changes

- Introduce a bilingual, server-rendered catalog for movies and series organized into user-defined collections.
- Add immutable metadata revisions from TMDB and Manual providers, including module-owned retention behavior and user overrides.
- Add manual torrent discovery through Prowlarr and idempotent submission to pluggable download-client instances, beginning with qBittorrent.
- Expose protected metadata, container-independent naming, and Jellyfin/Kodi NFO export APIs for external processors.
- Define independently testable metadata-provider and download-client module contracts.
- Provide a single-process SQLite deployment, external-auth security model, generic container example, and GitHub release pipeline.
- Explicitly exclude file scanning, muxing, moving, download-progress monitoring, Jellyfin invocation, runtime plugin installation, Usenet, multi-user roles, queues, and OpenAI integration from the MVP.

## Capabilities

### New Capabilities

- `catalog-and-metadata`: Collections, media identity, immutable revisions, localization, Manual metadata, and TMDB metadata behavior.
- `module-contracts-and-retention`: Static module packaging, conformance contracts, generic settings, secret references, and provider-owned retention.
- `torrent-acquisition`: Prowlarr search, memory-only result tokens, download-client destinations, qBittorrent submission, idempotency, correlation, and reconciliation.
- `metadata-naming-nfo-api`: Protected metadata endpoints, extension-independent Jellyfin naming, NFO export, expiry semantics, and stable API errors.
- `bilingual-web-ui`: Responsive catalog, add/detail/acquisition/settings flows, Russian and English localization, accessibility, sessions, and CSRF.
- `deployment-and-delivery`: Single-container runtime, SQLite migrations and readiness, generic Compose, CI, GHCR multi-architecture publishing, and SemVer tags.

### Modified Capabilities

None.

## Impact

The change creates the first product contract for an empty repository. It introduces a Python 3.13/FastAPI runtime, SQLite storage, provider and client integrations, public processor APIs, a server-rendered UI, container delivery, and contributor-facing module contracts. Media files and download-client progress remain outside the service boundary.
