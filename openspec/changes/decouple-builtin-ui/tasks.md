## 1. Workspace and public contracts

- [ ] 1.1 Add focused failing workspace/build tests for two independent wheels, packaged UI resources, and the prohibited-import boundary; observe the expected RED before changing package configuration.
- [ ] 1.2 Convert uv and pnpm configuration to the root backend, `media-finder-control-contracts`, and `media-finder-builtin-ui` workspaces; produce a frozen lock and make the focused wheel/resource tests GREEN.
- [ ] 1.3 Add focused failing contract tests for immutable DTOs, safe error representation, pagination, locale/status enums, the complete Manual v1 browser document and provider-schema parity, `ControlGateway`, and `BrowserSecurityPort`; implement only framework-independent public types and make them GREEN.
- [ ] 1.4 Add focused failing tests for a deterministic fake gateway and localhost development host covering catalog, series/specials, duplicate confirmation, integration failure, acquisition states, and both locales; implement the test/dev support and make them GREEN without backend imports.

## 2. Backend gateway and bounded state

- [ ] 2.1 Add focused failing tests for HMAC cursor signing, endpoint/filter binding, stable continuation, default 50, maximum 100, and tampering; implement the backend cursor codec and paged catalog/collection gateway operations to GREEN.
- [ ] 2.2 Add focused failing gateway tests for provider search, exact duplicates, cross-provider similarity confirmation, immutable revisions, metadata locale, and one-use metadata selections; move the selection cache behind the gateway and make them GREEN.
- [ ] 2.3 Add focused failing gateway tests for complete Manual create/edit/import, canonical existing-identity confirmation, lossless rich metadata, and atomic bounded CSV import; implement the Manual gateway operations and confirmation cache to GREEN.
- [ ] 2.4 Add focused failing gateway tests for release search, live system qBittorrent destinations, one-use release tokens, idempotent submission, timeout behavior, and reconcile without Prowlarr; implement acquisition gateway operations to GREEN.
- [ ] 2.5 Add focused failing gateway tests for safe environment diagnostics and attributions with set, missing, ready, and unavailable integrations; implement the diagnostic gateway operations without values or upstream bodies.
- [ ] 2.6 Run the gateway contract suite against real backend composition and confirm every expected domain/module failure becomes a stable `ControlFailure` without duplicating domain validation.

## 3. Browser security and HTTP control adapter

- [ ] 3.1 Add focused failing tests for compatible `mf_session` bootstrap, independent locale updates, cookie flags, constant-time CSRF comparison, reusable valid CSRF, invalid sessions, and unchanged payload compatibility; implement `BrowserSecurityPort` to GREEN.
- [ ] 3.2 Add focused failing HTTP tests for JSON-only mutations, one-megabyte body bounds, required same-origin `Origin`, foreign-origin rejection, absent CORS headers, request IDs, and safe framework errors; implement the shared control request boundary to GREEN.
- [ ] 3.3 Add focused failing route tests for session, collection, paged catalog, item detail, move, archive, and restore endpoints; implement their `/api/control/v1` adapters and validate gateway/HTTP parity.
- [ ] 3.4 Add focused failing route tests for metadata providers/search/selection, Manual import/confirmation/edit/CSV, exact duplicate, similarity, expiration, and redaction; implement those adapters and validate gateway/HTTP parity.
- [ ] 3.5 Add focused failing route tests for release search, destinations, submission, reconcile, diagnostics, and about/attribution; implement those adapters and preserve one-use/idempotency semantics.
- [ ] 3.6 Add a deterministic OpenAPI generation test, observe missing-schema RED, generate `docs/api/control-v1.openapi.json`, and make schema drift, processor-schema exclusion, and public error-model checks GREEN.

## 4. Built-in UI migration

- [ ] 4.1 Add failing compatibility tests for the current HTML route/method inventory, cookie behavior, redirect/fragment semantics, localization, and error codes using only fake ports; introduce the built-in UI composition/context on the public contracts and make the foundation GREEN.
- [ ] 4.2 Add focused HTML-versus-gateway parity tests for catalog, collections, archive/restore/move, poster fallback, details, and acquisition tabs; migrate the catalog route family and view models to the gateway and make them GREEN.
- [ ] 4.3 Add focused parity tests for provider search/confirmation, structured Manual create/edit/import/confirmation, rich field preservation, CSV atomicity, and locale independence; migrate the metadata/Manual route family and make them GREEN.
- [ ] 4.4 Add focused parity tests for release search, destination refresh, submission, stale destination recovery, pending reconcile, and safe failures; migrate the acquisition route family and make them GREEN.
- [ ] 4.5 Add focused parity tests for read-only integration diagnostics and provider attribution; migrate Settings/About to the gateway and make them GREEN.
- [ ] 4.6 Move templates, assets, gettext catalogs, i18n, form parsing, and presentation helpers into the built-in UI wheel; rebuild assets/catalogs and make wheel-resource, fake-host, forbidden-import, keyboard, axe, RU/EN, and zero-console/network-noise tests GREEN.
- [ ] 4.7 Remove obsolete UI repository/runtime/context paths and compatibility state hooks only after an architecture scan and full UI regression prove there is no direct backend path remaining.

## 5. Production composition and UI mode

- [ ] 5.1 Add focused failing lifecycle tests proving the root creates one engine/session/runtime/cache set, child apps do not own shared resources, and shutdown closes each resource exactly once; refactor production composition to GREEN.
- [ ] 5.2 Add focused failing runtime tests for missing/default `builtin`, explicit `builtin`, `disabled`, and invalid `MEDIA_FINDER_UI_MODE`; implement one-time mode parsing and conditional HTML/static mounting to GREEN.
- [ ] 5.3 Add composed-app regression tests proving default HTML paths, `/api/control/v1`, `/api/v1`, health, migrations, maintenance, and processor Bearer behavior coexist without route shadowing; make both UI modes GREEN without a database migration.

## 6. External UI, delivery, and documentation

- [ ] 6.1 Add a failing Playwright acceptance test for a minimal same-origin external page using session, catalog, metadata, Manual, destination, Acquisition, and reconcile control operations without CORS or a processor token; implement only the test fixture and required contract fixes until GREEN.
- [ ] 6.2 Update English documentation for control API compatibility, OpenAPI consumption, independent built-in UI development, default/disabled mode, trusted proxy origin handling, and generic same-origin Traefik routing; document rollback to `builtin` and the absence of cross-origin support.
- [ ] 6.3 Update `AGENTS.md` with the UI import boundary and mandatory OpenSpec, OpenAPI snapshot, gateway conformance, and browser-security checks for control-contract changes.
- [ ] 6.4 Add workspace wheel, architecture, control contract, OpenAPI drift, UI fake-host, and both-mode smoke steps inside the existing seven `verification/*` contexts; extend deterministic delivery validators without changing branch-protection check names.
- [ ] 6.5 Update the Docker build and generic Compose environment placeholder for `MEDIA_FINDER_UI_MODE=builtin`; prove the common image contains both workspace wheels and no additional service, port, volume, or media/download mount.

## 7. Final verification and review

- [ ] 7.1 Run frozen uv and pnpm installs, strict OpenSpec validation, documentation policy, format, lint, strict type checks, all unit/integration/gateway/contract/Playwright tests, independent wheel builds, asset/catalog rebuild with no diff, delivery validation, and available production image smoke checks.
- [ ] 7.2 Verify Alembic head and autogenerate drift are unchanged, a fresh database starts in both UI modes, secrets/raw provider data never enter control/OpenAPI responses, and `git diff --check` is clean.
- [ ] 7.3 Perform an independent architecture/security/acceptance review against every delta-spec scenario, fix all Critical and Important findings through focused RED/GREEN tests, and rerun the complete pristine verification matrix before marking the change ready for spec sync and archive.
