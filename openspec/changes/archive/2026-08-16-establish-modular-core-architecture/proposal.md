## Why

Media Finder already exposes replaceable metadata, download, and UI boundaries, but the backend SDK, first-party integrations, persistence, HTTP adapters, and application orchestration still share one Python distribution and several cross-cutting modules. Establishing enforceable package and ownership boundaries now, while there are no users or persistent upgrade obligations, prevents those internal conventions from becoming a permanent compatibility surface and preserves a practical path to independently evolve modules or replace the Python implementation later.

## What Changes

- Convert the repository into a package-enforced modular monolith with a minimal server host, a vertically organized core package, a public module SDK, the existing control-contract package, the built-in UI package, and one package per first-party integration.
- Define core-owned bounded contexts for catalog and metadata, acquisition, exports, module runtime, control orchestration, and platform concerns; persistence, transactions, opaque tokens, security, maintenance scheduling, and durable invariants remain exclusively core-owned.
- Introduce specialized and versioned module contracts for metadata providers, release providers, and download clients instead of a universal plugin interface; move Manual, TMDB, Prowlarr, and qBittorrent through the same public registry and conformance path.
- Add machine-readable module manifests that declare stable identity, module kind and version, SDK compatibility, contract version, capabilities, attribution, translations, and the exact environment variables required by the module.
- Publish deterministic language-neutral JSON Schema/OpenAPI artifacts and conformance fixtures alongside the current Python bindings so future implementations can preserve semantic contracts without preserving Python imports.
- Keep modules statically registered, reviewed, built into one image, and released with the product; runtime installation, hot loading, marketplaces, arbitrary hooks, module-owned database tables, and untrusted-code sandboxing remain out of scope.
- Preserve the supported browser control API, processor API, HTML routes, one-container deployment, and current product workflows while removing direct core-internal dependency paths.
- **BREAKING**: Replace the current internal `media_finder.sdk`, integration, ORM, and runtime import surfaces without compatibility shims. These Python internals are not supported external APIs, and the database may be rebuilt from a new initial migration because no persistent user data must be upgraded.

## Capabilities

### New Capabilities

- `modular-application-architecture`: Defines the package graph, core bounded-context ownership, dependency direction, composition root, language-neutral contract artifacts, and architectural enforcement required for the modular monolith.

### Modified Capabilities

- `module-contracts-and-retention`: Extends the public module system with release providers, machine-readable manifests, environment declarations, lifecycle ownership, language-neutral fixtures, and capability-specific conformance.
- `torrent-acquisition`: Replaces the Prowlarr-specific core acquisition boundary with a registered release-provider contract while preserving bounded opaque selections, artifact safety, and download-client submission semantics.
- `deployment-and-delivery`: Requires isolated workspace wheel builds, lockstep package assembly into the existing image, architecture checks, schema drift checks, and unchanged protected verification contexts.

## Impact

- Affects the root Python distribution, uv workspace, SDK and integration packages, composition/runtime code, SQLAlchemy/Alembic layout, control gateway implementation, processor adapters, tests, CI, Docker build, and contributor documentation.
- Adds first-party packages for core, module SDK, Manual, TMDB, Prowlarr, and qBittorrent while retaining the existing control-contract and built-in UI distributions.
- Does not add another process, container, database, queue, worker, runtime plugin loader, cross-origin UI mode, or independently versioned release train.
- Does not change Media Finder's product boundary: file scanning, muxing, moving, download monitoring, and Jellyfin invocation remain external responsibilities.
