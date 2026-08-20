## 1. Frontend Contract and Build Foundation

- [x] 1.1 Add focused failing architecture tests that reject browser imports outside presentation libraries and the checked-in control contract, and record the expected RED result.
- [x] 1.2 Add the `packages/builtin-ui/web` Vite and strict-TypeScript structure; pin exact compatible React, React Router, TanStack Query, Mantine, i18next, OpenAPI-client, lint, test, MSW, Playwright, and accessibility dependencies in the pnpm lockfile.
- [x] 1.3 Add a focused failing drift test for TypeScript generated from `docs/api/control-v1.openapi.json`, and record the expected RED result.
- [x] 1.4 Add deterministic OpenAPI type generation, check in the generated client types, and expose frontend format, lint, type, unit, browser, accessibility, build, and drift-check scripts through the pnpm workspace.
- [x] 1.5 Add focused failing delivery tests proving the frontend build precedes wheel and image assembly and that no Node runtime is required in the production image, and record the expected RED result.
- [x] 1.6 Update delivery/build orchestration to package only deterministic Vite output in the Python wheel and make the new delivery tests GREEN.

## 2. Static Host and Composition Boundary

- [x] 2.1 Add focused failing Python tests for packaged `index.html`, hashed assets, cache headers, supported SPA `GET`/`HEAD` fallback, missing assets, rejected mutation fallback, and `builtin|disabled` behavior; record the expected RED result.
- [x] 2.2 Replace the injected gateway/security UI factory with the minimal static ASGI host and make the static-host tests GREEN.
- [x] 2.3 Update the server composition root so the built-in host receives no backend, persistence, security, or integration object while `/api/control`, `/api/v1`, and `/health` retain their existing dispatch ownership.
- [x] 2.4 Adapt isolated-wheel tests to install the UI artifact without backend packages or Node and verify its static resources and presentation-only imports.

## 3. Typed Client, Session, Shell, and Localization

- [x] 3.1 Add failing Vitest/MSW tests for session bootstrap, in-memory CSRF injection on JSON mutations, cancellation, safe machine-error mapping, request identifiers, and the absence of processor requests or credentials; record the expected RED result.
- [x] 3.2 Implement the central typed `ControlClient`, TanStack Query provider, session bootstrap, mutation headers, and safe error normalization to make the client tests GREEN.
- [x] 3.3 Add failing component and Playwright tests for `/`, `/add`, `/items/:itemId`, `/items/:itemId/releases`, localized not-found behavior, English/Russian switching, desktop navigation, mobile drawer focus, and no horizontal overflow; record the expected RED result.
- [x] 3.4 Implement React Router Data Mode routes, the Mantine application shell, responsive navigation, route loading/error states, and accessible focus behavior.
- [x] 3.5 Implement English and Russian i18next catalogs, session-backed locale switching, invariant error-code localization, locale-sensitive query invalidation, and deterministic locale completeness checks.
- [x] 3.6 Add typed MSW fixtures and a Vite development mode for English, Russian, desktop, mobile, catalog, workflow, empty, loading, and safe-error states without storage or integration variables.

## 4. Catalog and Media Overview

- [x] 4.1 Add failing component and HTTP integration tests for cursor-based catalog loading, read-only collection filtering, `Uncategorized`, informative media cards, pending-state wording, and stable local artwork fallback; record the expected RED result.
- [x] 4.2 Implement the responsive poster catalog, collection navigation, cursor loading, acquisition-state labels, and local poster fallback to make the catalog tests GREEN.
- [x] 4.3 Add failing route tests for normalized movie and series overview pages with a `Find release` action and without season, episode, or Acquisition-history claims; record the expected RED result.
- [x] 4.4 Implement the media overview route and its localized loading, empty, missing-item, and safe-error states.

## 5. Metadata Search and Explicit Selection

- [x] 5.1 Add failing component and MSW tests for provider-scoped search, grouped provider results, explicit single selection, similarity confirmation, duplicate/already-saved outcomes, saving without download, and expired or consumed selection recovery; record the expected RED result.
- [x] 5.2 Implement metadata search and grouped results without cross-provider merging or automatic selection.
- [x] 5.3 Implement explicit selection, similarity confirmation, catalog save, memory-only selection-token handling, safe return to search, and the optional transition to `Find release`.

## 6. Release Search and Acquisition Submission

- [x] 6.1 Add failing component and MSW tests for release search, explicit release selection, expired selection recovery, immediately refreshed destinations, confirmation, and `pending`, `submitted`, and `failed` results; record the expected RED result.
- [x] 6.2 Add failing tests proving one `crypto.randomUUID()` idempotency key is reused by automatic retries but replaced for a new explicit confirmation; record the expected RED result.
- [x] 6.3 Implement release search and explicit memory-only release selection with localized safe recovery from invalid tokens.
- [x] 6.4 Implement live destination refresh, accessible confirmation, idempotent Acquisition submission, retry behavior, and result presentation without download-progress claims.

## 7. Direct Legacy Replacement

- [x] 7.1 Add failing composed-server tests proving supported bookmarks use `/api/control/v1`, legacy Jinja form and fragment mutations are rejected without state change, omitted secondary routes render localized not-found feedback, and browser traffic never reaches `/api/v1`; record the expected RED result.
- [x] 7.2 Add parity tests proving the supported browser workflow and direct control calls produce the same state transitions and invariant machine error codes without changing the checked OpenAPI snapshot.
- [x] 7.3 Remove Jinja templates, HTMX and manual-editor assets, form/manual/i18n helpers, the fake Python gateway, legacy locale catalogs, obsolete routes, and their superseded tests.
- [x] 7.4 Remove obsolete Jinja, Babel, HTMX, fake-gateway, and injected UI dependencies; update package metadata and architecture checks for the static presentation boundary.

## 8. Verification and Handoff

- [x] 8.1 Run focused frontend unit, component, MSW, Playwright, and axe checks for every changed scenario and resolve all failures.
- [x] 8.2 Run focused Python static-host, composition, browser-security, control-parity, OpenAPI, architecture, localization, and isolated-wheel tests and resolve all failures.
- [x] 8.3 Run frontend format, lint, strict type-check, generated-contract drift, clean production build, generated-asset drift, and packaged-asset checks from a clean build state.
- [x] 8.4 Update English developer/operator documentation for the JavaScript requirement, isolated UI development, production asset build, supported initial workflow, temporary omissions, deployment, and immutable-image rollback.
- [x] 8.5 Run `pnpm spec:validate`, documentation checks, Python format/lint/type/test, frontend verification, delivery tests/validation, isolated wheel verification, and production-image smoke checks with both UI modes; report any unavailable gate as `not run` or `blocked`.
