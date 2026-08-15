## Context

See `proposal.md` for motivation. The current `create_ui_app` constructs a SQLAlchemy engine, session factory, repository, module runtime, selection caches, templates, and browser security. UI route modules call repositories and domain services directly. The processor application separately constructs another engine, and the production runtime mounts it beneath the UI application. The only public JSON API is the Bearer-protected processor/export surface, which is intentionally unsuitable for browser catalog administration.

The approved constraints are a default single container and worker, unchanged HTML behavior, Jinja/HTMX preservation, same-origin replacement UIs, no CORS or new user database, no SQLite migration, and no second implementation path for business rules.

## Goals / Non-Goals

**Goals:**

- Make the built-in interface independently buildable and testable with deterministic fake control data.
- Give browser interfaces one versioned JSON contract backed by the same application gateway as HTML routes.
- Make the production runtime the only owner of database, integration, cache, and lifecycle resources.
- Preserve processor API, persistence, external-integration, HTML, localization, and default deployment compatibility.
- Make package boundaries, OpenAPI drift, same-origin security, and resource bounds mechanically enforceable.

**Non-Goals:**

- A SPA rewrite, official alternative UI, second image, second repository, cross-origin mode, user accounts, roles, service-token administration, or UI plugin loader.
- Independent runtime versions for workspace packages; the common image remains the release unit.
- Changes to normalized metadata, acquisition state, provider retention, naming, NFO, or integration environment declarations.

## Decisions

### Use three statically composed workspace packages

Convert the repository to a uv workspace with:

- the root `media-finder` backend distribution;
- `packages/control-contracts`, distribution `media-finder-control-contracts`, import package `media_finder_control`;
- `packages/builtin-ui`, distribution `media-finder-builtin-ui`, import package `media_finder_builtin_ui`.

The root distribution depends on both workspace distributions because the common image includes the default UI. `media-finder-builtin-ui` depends on `media-finder-control-contracts`, FastAPI/Starlette, Jinja2, and Babel but not on `media-finder`. The contracts package depends only on Pydantic and the standard library. The pnpm workspace keeps OpenSpec and delivery tooling at the root and gives the built-in UI its own asset-build package. Production templates, compiled locales, and static files are wheel data owned by the UI distribution.

An AST architecture test rejects imports from `media_finder`, SQLAlchemy, integration modules, or persistence libraries anywhere below the UI package. A distribution build test installs each wheel into an empty target and verifies imports plus packaged resources.

Alternative rejected: move files to another subpackage in the root distribution. It would leave dependency enforcement and independent build verification too weak. A separate service/repository is also rejected because there is no independent runtime lifecycle yet.

### Share framework-independent DTOs and ports

`media_finder_control` owns immutable Pydantic request/response models, pagination types, locale and status enums, a stable error representation, and asynchronous protocols:

- `ControlGateway` for catalog, metadata, Manual, acquisition, diagnostics, and attribution use cases;
- `BrowserSecurityPort` for loading, validating, and serializing signed browser-session state without exposing a signing key to the UI package.

The protocols accept and return typed values rather than FastAPI requests, SQLAlchemy objects, provider instances, or HTML. IDs are strings or UUID values, timestamps are UTC ISO-8601 in JSON, and locales are `en` or `ru`. Catalog and detail responses use control-specific safe projections rather than importing backend normalized-metadata classes. The contract package defines the complete versioned Manual v1 browser document; the backend maps it to the provider-owned normalized schema, and a JSON-schema parity test prevents either representation from silently dropping a supported field.

The backend implements both ports. `BackendControlGateway` owns transaction boundaries and delegates to the existing domain services and integrations. Its asynchronous methods run each existing synchronous database/integration operation in the application thread pool, creating and closing the SQLAlchemy session inside that worker context rather than blocking the event loop or moving a session between threads. It translates expected domain/module exceptions into `ControlFailure(code, status, safe_details)` and never returns localized prose. Existing services remain the source of domain behavior; the gateway does not copy their validation.

Alternative rejected: make the built-in UI call its own server through loopback HTTP or ASGI transport. That adds re-entrant request/session forwarding and lifecycle complexity to the default single worker. Direct port injection preserves one use-case implementation, while conformance tests prove the HTTP adapter and direct consumer expose identical results.

### Move all intermediate workflow state behind the gateway

Metadata selections, Manual confirmation drafts, release results, and confirmation state move from `UIContext` into backend-owned bounded `EphemeralCache` instances created by the runtime. Tokens remain cryptographically random, capacity and TTL bounded, process-local, restart-invalidated, and one-use when consumed. All missing, expired, evicted, consumed, and previous-process tokens map to HTTP 410 `selection_expired`.

List cursors are not stored in those caches. The backend creates domain-separated HMAC-signed cursors using the UI session secret. The payload includes API version, resource, normalized filters, stable ordering position, and a format version. It contains no secret or raw metadata. A cursor used with another endpoint or filter, or with an invalid signature, maps to 422 `cursor_invalid`. List endpoints default to 50 and reject limits above 100.

### Add one browser HTTP adapter without changing the processor adapter

Mount a dedicated FastAPI sub-application at `/api/control` with routes under `/v1` and OpenAPI at `/openapi.json`. Its externally visible schema is checked in at `docs/api/control-v1.openapi.json`, generated deterministically from the production composition, and compared byte-for-byte in CI after canonical JSON formatting.

The first version exposes these resource groups:

| Method and path | Use case |
| --- | --- |
| `GET /api/control/v1/session` | Bootstrap cookie, CSRF, and locale preferences |
| `PATCH /api/control/v1/session` | Change UI and metadata locale |
| `GET/POST /api/control/v1/collections` | List or create collections |
| `PATCH /api/control/v1/collections/{id}` | Archive or restore a collection |
| `GET /api/control/v1/media-items` | Page active, archived, collection, or uncategorized items |
| `GET/PATCH /api/control/v1/media-items/{id}` | Read detail or move/archive/restore an item |
| `GET /api/control/v1/metadata-providers` | List available providers and attribution identifiers |
| `POST /api/control/v1/metadata-searches` | Search configured providers and issue result tokens |
| `POST /api/control/v1/metadata-selections/{token}` | Confirm one provider result, including similarity confirmation |
| `POST /api/control/v1/manual-imports` | Create/import a Manual document or issue duplicate confirmation |
| `POST /api/control/v1/manual-imports/{token}/confirm` | Consume an existing-identity confirmation |
| `PUT /api/control/v1/media-items/{id}/manual-metadata` | Losslessly edit a Manual item or issue confirmation |
| `POST /api/control/v1/media-items/{id}/episode-imports` | Apply a bounded atomic CSV episode import carried as a JSON string field |
| `POST /api/control/v1/media-items/{id}/release-searches` | Search Prowlarr and issue safe one-use result tokens |
| `GET /api/control/v1/download-destinations` | Return current environment-owned qBittorrent categories |
| `POST /api/control/v1/acquisitions` | Submit one release token with destination and idempotency key |
| `POST /api/control/v1/acquisitions/{id}/reconcile` | Reconcile by exact client correlation without Prowlarr |
| `GET /api/control/v1/integrations` | Return safe declaration/readiness diagnostics |
| `GET /api/control/v1/about` | Return attribution and build information |

`PATCH` inputs use explicit optional fields plus an operation enum where omission would be ambiguous; they never accept arbitrary model dictionaries. Exact duplicates return 200 with the existing item. New resources return 201. Similarity and existing Manual identity return 409 `confirmation_required` with an opaque confirmation token. Invalid input returns 422. Integration unavailability returns 503 with a safe code. Every error uses `{ "error": { "code", "request_id", "details" } }`.

The processor app remains mounted at `/` after the explicit health, control, built-in HTML, and static routes, preserving `/api/v1/*` and its independent Bearer middleware. The control OpenAPI never contains processor schemas or its token.

### Centralize browser security and preserve the cookie

Move signing and CSRF primitives behind the backend `BrowserSecurityPort` while preserving cookie name `mf_session`, compatible payload keys, signature algorithm, path, and flags. The built-in UI passes hidden form tokens through the port. The control adapter sets the same cookie and returns the token in the session bootstrap body.

Unsafe control requests require all of:

- `application/json` with the existing one-megabyte bounded body policy;
- a valid signed session cookie;
- `X-CSRF-Token` equal under constant-time comparison to the session value;
- an `Origin` exactly equal to the effective ASGI scheme and authority after trusted proxy normalization.

No CORS middleware or `Access-Control-Allow-Origin` response is added. A missing/foreign origin, missing/invalid token, or invalid session returns 403 with a stable code and no mutation. CSRF is reusable for the unchanged session because multiple tabs and concurrent forms are supported; consuming workflow tokens remains one-use. UI and metadata locale updates do not rotate CSRF or invalidate other tabs.

External proxy authentication remains outside Media Finder and must protect both the frontend and `/api/control`. Health stays unauthenticated; `/api/v1` keeps Bearer authentication.

### Make the root runtime the only infrastructure composition root

Refactor factories so `runtime.create_application` constructs one engine, session factory, runtime factory, system qBittorrent row, caches, browser security implementation, gateway, maintenance runner, control app, processor app, and optional UI app. Child application factories receive these resources and never create or close shared infrastructure. One root lifespan owns startup and reverse-order shutdown.

`MEDIA_FINDER_UI_MODE` is parsed once before application construction. Missing or the exact lowercase value `builtin` mounts the UI HTML/static routers. The exact lowercase value `disabled` omits them. Any other value fails before Uvicorn starts. Control, processor, health, migrations, and maintenance are composed identically in both modes.

The standalone test factories remain explicit harnesses that construct resources through a shared composition fixture; production ownership is never inferred from `app.state` compatibility hooks.

### Preserve HTML as a presentation adapter

Move templates, assets, locales, i18n helpers, HTML route modules, form parsing, poster fallback, and view-model translation into `media_finder_builtin_ui`. Replace `UIRepository`, `RuntimeResolver`, session factories, and direct service calls in route context with `ControlGateway` and `BrowserSecurityPort` calls.

Every existing HTML method/path remains registered. The HTML adapter translates control DTOs into template view models and stable failure codes into gettext messages. It cannot create a different transaction or validation path. HTMX fragments and ordinary form posts retain their current response/redirect semantics.

The UI package includes `media-finder-ui-dev`, bound by default to `127.0.0.1:8001`. It injects a deterministic in-memory fake gateway covering movie, series/special, duplicate, unavailable integration, pending/submitted/failed acquisition, and English/Russian states. The fake is development/test support and is not selected by production configuration.

### Keep one release unit and existing protected check names

The root CI commands orchestrate workspace formatting, typing, unit, contract, browser, asset, wheel, and image tests. The existing seven `verification/*` jobs remain the externally required contexts; package-specific steps are added within them. Production smoke runs default and disabled UI modes. A browser acceptance fixture serves a minimal same-origin external page and exercises session, catalog, metadata, Manual, destination, acquisition, and reconcile API operations without a processor token.

Documentation includes the control API, package development commands, OpenAPI compatibility policy, and a generic Traefik path-routing example. It does not add private domains, network names, or another Compose service to the default example.

## Risks / Trade-offs

- **[Large boundary migration can create parallel behavior]** → Migrate each HTML route family to the gateway before deleting its direct dependency, require parity tests, and reject any remaining prohibited import before completion.
- **[Shared DTO package can become a dumping ground]** → Keep only wire types and consumer-facing ports there; persistence, provider payloads, localization, and implementation helpers stay in their owners.
- **[Cursor format can accidentally become public data]** → Treat it as opaque, version and sign it, bind it to query semantics, and expose only `next_cursor` behavior.
- **[Origin checks can break a reverse proxy]** → Base comparison on the effective ASGI origin after trusted proxy handling and document the required forwarded scheme/host configuration.
- **[UI-disabled routing can shadow APIs]** → Register explicit control, processor, and health routes independently and test both modes at the composed-app and image-smoke boundaries.
- **[OpenAPI snapshot creates review noise]** → Canonicalize JSON deterministically and fail only on semantic generation drift, not timestamps or ordering.
- **[Workspace packaging increases build configuration]** → Add only two packages, keep one lock and release unit, and prove each wheel in an empty install target.

## Migration Plan

1. Convert build tooling to uv and pnpm workspaces while the root package still owns runtime behavior.
2. Introduce contracts, gateway, fake gateway, and conformance tests without exposing a second domain implementation.
3. Add browser security and control HTTP adapter, then generate and review the initial OpenAPI v1 snapshot.
4. Move one HTML route family at a time to the gateway, preserving focused RED/GREEN and browser parity evidence.
5. Move presentation files into the built-in UI distribution and enforce the import boundary.
6. Centralize root resource ownership, add UI mode, update CI/docs, and run both production smoke modes.
7. Deploy with the default `builtin` mode; no database migration or persistent conversion occurs.

Rollback uses the previous image and unchanged `/data`. If an operator enabled an external UI, setting `MEDIA_FINDER_UI_MODE=builtin` and recreating the current container restores the bundled interface before or independently of image rollback.
