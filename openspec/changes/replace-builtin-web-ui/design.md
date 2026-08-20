## Context

See `proposal.md` for the motivation and `specs/bilingual-web-ui/spec.md` for the replacement behavior. The current `packages/builtin-ui` wheel owns Jinja templates, HTMX form and fragment routes, gettext catalogs, a fake Python gateway, and browser tests. The server mounts `/api/control` before the root dispatcher and currently injects the control gateway and browser-security port into the UI application. The checked-in `docs/api/control-v1.openapi.json` already defines the only supported external browser boundary.

The replacement must retain the independently buildable UI package, one Python process and container, `MEDIA_FINDER_UI_MODE=builtin|disabled`, same-origin cookies and CSRF, processor isolation, and the package-dependency graph. No database, module, control-contract, or deployment migration is required.

## Goals / Non-Goals

**Goals:**

- Make the browser client statically type-checked against the checked-in control OpenAPI document and keep its runtime dependency surface presentation-only.
- Produce deterministic, wheel-packaged static output with isolated development fixtures and reproducible drift checks.
- Keep session credentials and opaque selection tokens out of persistent browser storage and preserve the existing backend security semantics.
- Remove the parallel server-rendered presentation path in the same change while preserving supported GET bookmarks.

**Non-Goals:**

- Introducing a frontend service, server-side rendering, a Node production runtime, CORS, offline support, or a general-purpose frontend platform.
- Changing `/api/control/v1`, `/api/v1`, persistence, module ownership, integration configuration, or secret handling.
- Retaining Jinja routes as a compatibility mode or implementing the secondary workflows excluded by the delta specification.

## Decisions

### 1. Keep the existing package and production topology

The TypeScript source will live under `packages/builtin-ui/web/`. Vite will emit deterministic hashed assets and `index.html` into a package resource directory under `packages/builtin-ui/src/media_finder_builtin_ui/static/`; the built wheel and application image will contain that output. The Python part of `media-finder-builtin-ui` becomes a small ASGI static host. It will serve known assets directly and return `index.html` only for non-reserved `GET` and `HEAD` client routes. API, processor, and health dispatch remain owned by the server composition root.

The UI factory will no longer accept a gateway, browser-security port, or secure-cookie option. Browser sessions are created and validated by `/api/control/v1/session`; the UI host owns no domain or security behavior. `index.html` will be served with revalidation/no-cache semantics, while content-hashed assets may use long-lived immutable caching.

This is the lowest sufficient architecture rung: the existing package changes implementation, but no process or service is added. A separate frontend container or SSR framework would add routing, health, deployment, and authentication ownership without benefiting this self-hosted application.

### 2. Use a client-rendered React and TypeScript stack

The frontend will use exact compatible patch versions, recorded in `pnpm-lock.yaml`, from these release lines:

- React 19.2 with strict TypeScript for components and application code.
- Vite 8 for the development host and production build.
- React Router 7 in Data Mode for the four supported bookmarkable routes and route-level loading and error behavior.
- TanStack Query for server-state caching, cancellation, invalidation, and mutation state.
- Mantine 9 plus CSS Modules for accessible controls, responsive primitives, theming, and application-specific layout.
- i18next with react-i18next for English and Russian catalogs.
- openapi-typescript plus openapi-fetch for generated contract types and the small HTTP transport.

The apply phase will resolve and pin mutually compatible exact versions rather than accepting floating ranges. Tailwind is excluded because Mantine and CSS Modules cover the MVP styling needs without a second styling system. Redux and another client store are excluded because route state, local component state, and TanStack Query cover the required state classes. Next.js, Nuxt, and other SSR/meta-frameworks are excluded because the product has no SSR, public SEO, or Node-runtime requirement. Storybook is deferred; deterministic mocked routes and component tests provide the required isolated state coverage with less infrastructure.

### 3. Generate types from the public control contract and centralize transport

`docs/api/control-v1.openapi.json` is the input to a deterministic generation command. Generated TypeScript types are checked in beside the browser source so drift is reviewable; CI regenerates them and rejects a diff. A single `ControlClient` wraps openapi-fetch with the fixed same-origin `/api/control` base path, JSON headers, CSRF injection for mutations, request cancellation, and normalized safe failures. Feature hooks may depend on this client and generated shapes; they may not import Python sources or reproduce backend DTOs manually.

The client first calls the session endpoint. The HttpOnly cookie remains inaccessible to JavaScript, while the returned CSRF token is retained only in memory. Machine error codes and request identifiers drive localized feedback; upstream messages and sensitive URLs are never rendered. No processor endpoint or credential is represented in the client.

Changing the control contract is not expected. If implementation reveals a missing endpoint or field, apply stops and the change is revised through `openspec-update-change`, including the required OpenAPI and conformance work.

### 4. Separate server state, navigation state, and ephemeral workflow state

TanStack Query owns control-API server state. React Router owns route and URL search state, including catalog filters and supported bookmarks. Component state owns transient UI concerns such as drawer visibility and confirmation steps. This avoids a second global state system.

Metadata and release selection tokens remain memory-only and are discarded after successful consumption. An expired, consumed, evicted, or restart-invalidated token produces localized feedback and returns the user to the corresponding search. Acquisition confirmation creates one `crypto.randomUUID()` idempotency key; automatic retries reuse it, while a new explicit confirmation creates a new key. Destinations are refreshed immediately before confirmation so the submitted destination comes from current backend state.

### 5. Keep localization in the browser without duplicating module catalogs

English and Russian JSON resources will contain presentation strings and invariant control-error mappings. The session response selects the UI and metadata locales; changing locale uses the existing session mutation and then invalidates locale-sensitive queries. Provider/module attribution and translated module values continue to arrive through the control API. The browser bundle will not copy first-party module translation catalogs.

Python gettext/Babel UI catalogs and helpers are removed with the Jinja implementation. Locale completeness, forbidden Russian developer prose, interpolation safety, and missing-key behavior remain deterministic checks adapted to the JSON catalogs.

### 6. Use deterministic HTTP fixtures for isolated development

The Vite development host uses Mock Service Worker handlers built from the generated control types. Named fixtures cover catalog, metadata results from multiple providers, similarity confirmation, release results, destinations, Acquisition states, safe failures, English, Russian, desktop, and mobile. The handlers model the public HTTP contract rather than a second Python gateway and never require storage, module credentials, or external network access.

Vitest and React Testing Library cover pure behavior and components; MSW covers HTTP-level client integration; Playwright exercises supported routes and the critical path. Composed-server Playwright tests remain responsible for real cookie, CSRF, routing, and control parity. axe-core runs against representative routed states. These layers replace the fake gateway, HTML contract tests, and server-template browser suite.

### 7. Treat generated assets as reviewed package inputs

The repository will expose frontend format, lint, type-check, unit-test, browser-test, accessibility, contract-generation, build, and drift-check commands through the pnpm workspace. A clean production build replaces the generated static directory, and a verification command rebuilds into a temporary location or checks the worktree diff. Wheel tests install the artifact in isolation and verify `index.html`, hashed assets, supported SPA fallback, cache headers, and absence of source-only dependencies. Delivery validation ensures the frontend build runs before the Python wheel and image are assembled.

Checking generated assets into the wheel source keeps Python packaging and the production image independent of Node at runtime and preserves reproducible source distributions. The cost is larger reviews; deterministic generation and drift checks make that cost explicit.

### 8. Replace the legacy presentation atomically

The change removes Jinja templates, HTMX/manual scripts, Python form decoding, UI gettext helpers and catalogs, fake gateway code, and their obsolete dependencies and tests. Supported GET paths are handled by the SPA fallback and React Router. Removed form, fragment, and secondary routes return an unsupported response and never fall through to a hidden legacy mutation path.

There is no dual-mode flag beyond the existing `builtin|disabled` setting and no compatibility shim. Running both implementations would duplicate presentation and domain orchestration paths and make rollback behavior ambiguous.

### 9. Preserve ownership and secret boundaries

The server composition root continues to own concrete services, integrations, persistence, and both API applications. The control application continues to own the signed HttpOnly session cookie, CSRF validation, safe errors, and control orchestration. The processor application continues to own processor-token validation and is never called by the browser. The built-in UI owns only packaged static files and browser presentation.

No new secret or environment variable is introduced. Existing provider and download-client variables remain declared and resolved by their modules; neither references nor values enter generated fixtures, bundles, logs, or browser storage.

## Risks / Trade-offs

- [The built-in UI now requires JavaScript] -> Keep server health and control APIs independent, show a minimal static bootstrap failure message, and document the requirement.
- [The initial replacement intentionally removes useful secondary screens] -> Keep their control endpoints unchanged, present localized not-found behavior, document the temporary limitation, and restore them only through later approved increments.
- [Generated types or assets can become stale] -> Provide deterministic generation commands and fail CI on a regenerated diff.
- [A root SPA fallback can mask invalid routes or assets] -> Restrict fallback to non-reserved `GET` and `HEAD` routes, serve known assets explicitly, and test API, health, missing-asset, and legacy mutation behavior.
- [Opaque workflow tokens are lost on reload and can expire] -> Keep them out of persistent storage by design and return users safely to search with localized guidance.
- [Large component-framework upgrades can cause churn] -> Pin exact compatible versions, keep application layout in CSS Modules, and avoid framework-specific data or domain abstractions.
- [External poster images can fail or affect layout] -> Use stable dimensions, lazy loading, and a local fallback without proxying or persisting remote artwork.
- [Atomic replacement gives no in-image UI rollback] -> Preserve the unchanged control API and deploy the previous immutable image; do not create a second live presentation path.

## Migration Plan

1. Add the typed frontend build, generated control types, deterministic fixtures, and failing boundary/static-host tests without changing production routing.
2. Implement the minimal static host and supported SPA routes, then build the catalog-to-Acquisition workflow behind the existing built-in package boundary.
3. Adapt composed browser, security, accessibility, wheel, delivery, and image checks; prove the control OpenAPI snapshot and backend semantics are unchanged.
4. Remove the legacy implementation and dependencies only after the replacement tests cover supported bookmarks, rejected legacy mutations, and the critical path.
5. Build and verify the immutable application image with `MEDIA_FINDER_UI_MODE=builtin` and `disabled`, then deploy through the normal image replacement process.

No database or environment migration is needed. Roll back by redeploying the previous immutable image. Because API and stored-data contracts do not change, rollback requires no data transformation.
