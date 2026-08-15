## 1. Freeze Behavior and Establish Architecture Gates

- [x] 1.1 Reconfirm before production edits that no persistent deployment data must survive; record the disposable-database reset in operator/developer guidance, and stop for `openspec-update-change` if that assumption is false.
- [x] 1.2 Run and record the current locked install, full pytest/Playwright suite, control OpenAPI snapshot, processor API behavior, asset build, fresh Alembic migration, and composed-app smoke as the characterization baseline.
- [x] 1.3 Add focused architecture tests for the approved distribution graph, prohibited imports, explicit public exports, source-layout isolation, absence of runtime module discovery, and one composition owner; run them to RED against the current combined backend.
- [x] 1.4 Add behavior-preservation tests for control and processor routes, HTML paths, UI modes, error envelopes, CSRF/cookies, localization, and integration diagnostics that would catch accidental changes during file movement; prove they are GREEN before restructuring.

## 2. Create the Workspace and Public Module SDK

- [x] 2.1 Add RED package-build tests for a virtual root workspace plus independently installable `media-finder`, `media-finder-core`, and `media-finder-module-sdk` wheels with `py.typed`, explicit `__all__`, and no undeclared source-tree imports.
- [x] 2.2 Convert the root to a virtual uv workspace, add `apps/server`, `packages/core`, and `packages/module-sdk` source-layout distributions, preserve the existing control/UI distributions, and make the focused wheel tests GREEN without moving live behavior yet.
- [x] 2.3 Add RED SDK tests for value-free `module.toml` loading, stable module identity, specialized kinds, semantic versions, SDK ranges, contract versions, capabilities, attribution, translation keys, exact environment declarations, duplicate/conflict rejection, and redacted immutable resolved values.
- [x] 2.4 Implement the manifest, environment, registration, stable error, lifecycle, and immutable DTO foundations in `media-finder-module-sdk`; keep FastAPI, SQLAlchemy, Jinja, httpx, core, and control contracts out of its dependency graph and make the focused tests GREEN.
- [x] 2.5 Add RED capability tests for `MetadataProvider`, configuration-free metadata retention, `ReleaseProvider`, and `DownloadClient`, including unsupported capability/kind combinations, standardized failures, lifecycle cleanup, and the absence of universal hooks or module lookup.
- [x] 2.6 Implement the three synchronous specialized protocols, registrations, closeable lifecycle, capability-aware conformance runners, and public fixture types; make all SDK contract tests GREEN in an environment where core is not installed.
- [x] 2.7 Add deterministic module manifest/DTO JSON Schema generation and checked v1 artifacts under `schemas/module-sdk/v1`; add semantic drift and byte-stability tests and make them GREEN.
- [x] 2.8 Add RED SDK tests for an optional typed `MetadataEditor` sub-capability covering structured import, identity validation, bounded episode-table merge, standardized errors, lifecycle cleanup, capability/factory mismatch, and absence of core/control dependencies.
- [x] 2.9 Implement `MetadataEditor`, immutable import/merge DTOs, typed optional metadata registration factory, conformance fixtures, and updated v1 schema artifacts; make focused tests GREEN without adding a universal extension map or concrete provider name to core.

## 3. Extract First-Party Modules Through the SDK

- [x] 3.1 Add RED isolated-wheel and metadata/editor-conformance tests for the Manual package, including its empty environment contract, in-memory fixture search/fetch, normalization, structured JSON identity validation, atomic episode CSV merge, standardized invalid-identity error, attribution, and configuration-free retention behavior.
- [x] 3.2 Move Manual into `media-finder-metadata-manual`, add its `module.toml`, public `registration()`, and typed metadata editor, make its focused tests GREEN, update consumers to the new package, and remove the old Manual module source in the same slice.
- [x] 3.3 Add RED isolated-wheel and metadata-conformance tests for TMDB covering exact `TMDB_TOKEN`, official-origin validation, movie/series/special fixture fetches, locale/identity, normalization/artwork, retention/expiry, export warnings, redaction, and resource closure.
- [x] 3.4 Move TMDB into `media-finder-metadata-tmdb`, add its `module.toml` and public `registration()`, make focused tests GREEN, update consumers, and remove the old TMDB module source without a compatibility import.
- [x] 3.5 Add RED release-provider conformance tests for Prowlarr covering exact environment declarations, configured base-path confinement, torrent-only bounded search, safe snapshots, opaque internal resolution values, magnet/torrent resolution, size limits, secret-safe errors/logging, and transport closure.
- [ ] 3.6 Move Prowlarr into `media-finder-release-prowlarr`, implement the public ReleaseProvider registration and fixtures, make focused tests GREEN, update acquisition consumers to the specialized contract, and delete the core-special Prowlarr adapter.
- [ ] 3.7 Add RED isolated-wheel and download-client conformance tests for qBittorrent covering exact environment declarations, URL/auth validation, isolated cookies, live categories, magnet/torrent capabilities, exact correlation, ambiguous timeouts, lookup, redaction, and lifecycle cleanup.
- [ ] 3.8 Move qBittorrent into `media-finder-download-qbittorrent`, add its `module.toml` and public `registration()`, make focused tests GREEN, update consumers, and remove the old qBittorrent module source without a compatibility import.
- [ ] 3.9 Add RED registry tests proving Manual, TMDB, Prowlarr, and qBittorrent use one host-supplied immutable typed registry, reject duplicate/conflicting manifests, receive only declared environment values, and close failed-attempt resources without affecting successful siblings.
- [ ] 3.10 Implement the host registry assembly and core module-runtime lifecycle to make the registry tests GREEN; ensure core contains no concrete integration names or imports and every first-party wheel passes its public conformance suite independently.

## 4. Establish Core Bounded Contexts

- [ ] 4.1 Add RED import and application-port tests for catalog, acquisition, exports, module runtime, control, and platform contexts, including a prohibition on cross-context ORM imports/relationships and direct `Session` use from command/query services.
- [ ] 4.2 Move catalog identity, collections, immutable metadata revision rules, duplicate/similarity handling, archive behavior, and catalog queries into `media_finder_core.catalog` behind focused repository/query ports; preserve current tests and make the catalog architecture slice GREEN.
- [ ] 4.3 Move metadata-editor orchestration, provider fetch/normalize orchestration, overrides, current-revision selection, and generic provider-owned retention execution into catalog application services; inject the selected editor without a concrete module identifier, validate SDK outputs before persistence, and make existing Manual atomicity/retention tests GREEN.
- [ ] 4.4 Move Acquisition state, idempotency, safe snapshots, exact correlation, timeout recovery, manual reconcile, and bounded opaque release selection into `media_finder_core.acquisition`; consume catalog through declared read ports and make focused acquisition tests GREEN.
- [ ] 4.5 Replace Prowlarr-specific acquisition branches with the selected ReleaseProvider registration while preserving one-use TTL tokens, payload bounds, first-party Prowlarr behavior, and the selected qBittorrent client; make release-search and submission integration tests GREEN.
- [ ] 4.6 Move normalized metadata, naming, NFO, expiry warnings, multi-episode rules, and current/pinned processor use cases into `media_finder_core.exports`; read catalog/acquisition snapshots through ports and make processor contract tests GREEN without exposing raw payloads or ORM records.
- [ ] 4.7 Move database/session construction, transactions/savepoints, maintenance cadence, safe errors, configuration, caches, and clocks into `media_finder_core.platform`; retain a single transaction owner and make failure-isolation/readiness tests GREEN.

## 5. Replace Persistence with the Clean Core Schema

- [ ] 5.1 Add RED schema tests for context-owned tables, immutable revision/acquisition snapshots, release/download module ID and version fields, foreign-key integrity without cross-context ORM navigation, and the absence of `app_settings`, mutable client instances, integration configuration, and environment references.
- [ ] 5.2 Split SQLAlchemy records and repositories by owning core context, remove cross-context relationships, persist only scalar IDs and immutable boundary values, and make repository/application tests GREEN.
- [ ] 5.3 Replace legacy Alembic revisions with one new pre-release initial migration that creates catalog, acquisition, and maintenance records; fail safely for unsupported old revision state and document recreation of disposable `/data`.
- [ ] 5.4 Run fresh upgrade, schema-drift/autogenerate, WAL, foreign-key, readiness, immutability, idempotency, retention savepoint, and acquisition snapshot tests to GREEN against the new initial schema.

## 6. Decompose Control Orchestration and Build the Server Host

- [ ] 6.1 Add RED tests requiring context-specific catalog, metadata, acquisition, and diagnostic control services plus a small `ControlGateway` facade that has no ORM, concrete module, environment, or FastAPI imports.
- [ ] 6.2 Decompose the existing backend gateway into those core control services and facade, preserve control DTO/error/pagination/token semantics, make real-gateway and HTTP-adapter conformance tests GREEN, and delete superseded gateway internals.
- [ ] 6.3 Add RED composition tests requiring `apps/server` to be the only concrete composition root and requiring child factories to receive rather than create shared engine, sessions, services, caches, security, modules, and maintenance resources.
- [ ] 6.4 Move FastAPI control, processor, health, browser-session, migration/startup, and CLI adapters into `media_finder_server`; explicitly assemble core, first-party registrations, and optional built-in UI, then make route and composition tests GREEN.
- [ ] 6.5 Implement one root lifespan with dependency-order startup and reverse-order shutdown for database, module instances, maintenance, and HTTP resources; cover successful reuse, partial construction failure, concurrent attempts, and both `builtin` and `disabled` UI modes.
- [ ] 6.6 Remove the legacy root `src/media_finder` implementation and old import surfaces after all consumers move; add negative tests proving no compatibility shim, duplicated runtime path, concrete-core integration import, or child-owned infrastructure remains.

## 7. Preserve Serialized and Browser Boundaries

- [ ] 7.1 Generate a deterministic processor OpenAPI v1 artifact alongside the existing control OpenAPI snapshot; add RED drift tests, then preserve current paths, schemas, authentication, status codes, stable errors, naming/NFO behavior, and expiry warnings until both snapshots are GREEN.
- [ ] 7.2 Run built-in UI unit and browser suites solely with its fake gateway and control-contract wheel; prove it installs without core/modules/SQLAlchemy, preserves EN/RU, forms, HTML paths, keyboard/axe behavior, and loads no module HTML/JavaScript.
- [ ] 7.3 Run the same browser control conformance scenarios against the real core facade and HTTP adapter, including CSRF replay/foreign-origin failures, opaque token expiry/eviction/single use, metadata/manual flows, release search, destinations, submission, and reconcile.
- [ ] 7.4 Add serialized conformance fixtures for all three module kinds and validate them independently of Python core imports, including success, missing configuration, standardized failures, locale/identity, retention, release bounds, safe snapshots, artifact capabilities, correlation, and redaction.

## 8. Delivery, Documentation, and Contributor Workflow

- [ ] 8.1 Update uv workspace metadata, lockfile, type/lint/test discovery, package data, asset/localization builds, and wheel metadata so every distribution builds reproducibly from the same product version and lock.
- [ ] 8.2 Extend the existing reusable GitHub verification workflow with isolated wheel installs, architecture rules, three module conformance suites, manifest/JSON Schema/processor OpenAPI drift, clean schema migration, and both UI-mode smokes while preserving all seven required `verification/*` contexts.
- [ ] 8.3 Update the multi-stage Docker build to build and install wheels rather than workspace source paths; prove the production image includes module manifests, fixtures needed at runtime, templates, catalogs, static assets, migrations, and only one non-root application process.
- [ ] 8.4 Update Compose and environment documentation from the first-party manifests without adding private infrastructure, runtime plugin mounts, another service, or persisted integration configuration.
- [ ] 8.5 Write English architecture and module-authoring documentation covering package ownership, dependency graph, `module.toml`, public registrations, exact environment declarations, trust limits, conformance, schema artifacts, first-party composition, lifecycle, and triggers for out-of-process modules.
- [ ] 8.6 Update `AGENTS.md` and project skills for the new paths and rules, add an `adding-release-provider` skill, and update metadata/download/schema skills so future changes require the appropriate OpenSpec delta, manifest, fixture, conformance, serialized artifacts, architecture checks, and tests.

## 9. Final Verification and Apply Handoff

- [ ] 9.1 Run frozen uv and pnpm installs, strict OpenSpec validation, documentation-language policy, format, lint, strict type checks, all isolated wheel builds/imports, architecture tests, module conformance, schema/OpenAPI drift, full pytest coverage, Playwright, assets/locales, delivery validators, and production Docker build/smoke.
- [ ] 9.2 Run a fresh-database end-to-end smoke for built-in and disabled UI modes, verify health/control/processor contracts, confirm Prowlarr-to-qBittorrent acquisition with fakes, and prove all resources close cleanly.
- [ ] 9.3 Scan the final tree for prohibited dependencies, old `media_finder` SDK/integration/runtime imports, compatibility shims, duplicate business paths, module-owned persistence/routes/assets, undeclared environment reads, stale migration references, and generated-artifact drift; resolve every finding before checking the task complete.
- [ ] 9.4 Reconcile every proposal/spec scenario to focused or integration evidence, record the no-data migration decision and exact verification results, keep implementation and planning artifacts consistent through `openspec-update-change` if required, and present the completed active change for independent review before spec sync/archive.
