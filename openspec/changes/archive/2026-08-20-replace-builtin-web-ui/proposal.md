## Why

The current Jinja2/HTMX interface proves the product workflows but makes a polished, responsive, API-first browser experience increasingly costly to evolve. Media Finder already exposes a stable same-origin browser control API, so the built-in interface can become a modern typed client without adding a second production process or crossing backend ownership boundaries.

## What Changes

- Replace the built-in Jinja2/HTMX presentation with a responsive TypeScript single-page application compiled to static assets and served by the existing built-in-UI package in the existing application process and container.
- Consume only the checked-in `/api/control/v1` OpenAPI contract from browser code; keep catalog, metadata, release, Acquisition, persistence, security, and integration behavior owned by the existing backend.
- Deliver the first replacement UI around the supported path `catalog -> metadata search and selection -> media detail -> release search and selection -> live destination -> Acquisition submission`, including English and Russian localization, safe error feedback, keyboard access, and desktop/mobile layouts.
- Preserve `MEDIA_FINDER_UI_MODE=builtin|disabled`, same-origin session and CSRF behavior, external reverse-proxy authentication, processor API isolation, one-container deployment, and rollback by deploying the previous image.
- Add deterministic frontend build, type, unit, browser, accessibility, OpenAPI-drift, packaged-wheel, and image verification.
- **BREAKING**: Remove the legacy Jinja HTML form actions and server-rendered fragment routes instead of maintaining a parallel compatibility path. Existing GET bookmarks for the catalog, add flow, media detail, and release selection remain supported as client routes.
- **BREAKING**: During the initial replacement release, Manual create/edit/import, episode CSV import, collection and item mutations, Acquisition history/reconciliation, integration diagnostics, Settings, and About are not exposed by the built-in UI. Their `/api/control/v1` capabilities remain unchanged for later UI increments and external clients.
- Do not add SSR, a separate frontend runtime or container, CORS, application user accounts, PWA/offline behavior, a second state-management layer, or a permanent legacy-UI fallback.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `bilingual-web-ui`: Replace the server-rendered compatibility contract with a bundled API-driven client, define the initial replacement workflow and responsive/localized behavior, and explicitly remove legacy form-route compatibility and temporarily unavailable secondary UI workflows.

## Impact

- Reworks `packages/builtin-ui` from Jinja templates, form handlers, gettext catalogs, and HTMX assets into a TypeScript source package plus a minimal Python static-asset host whose deterministic output remains packaged in the independently buildable wheel.
- Changes server composition only at the built-in presentation factory boundary; `/api/control/v1`, `/api/v1`, health endpoints, security ports, core services, module contracts, storage, and database schema remain unchanged.
- Adds pinned frontend presentation, routing, query, localization, OpenAPI client-generation, lint, test, and build dependencies to the existing pnpm workspace and lockfile.
- Updates UI architecture checks, generated-asset validation, isolated wheel tests, browser acceptance, delivery validation, production-image smoke checks, and operator/developer documentation.
- Requires no data migration. Rollback is the previous immutable application image because this change intentionally does not ship both UI implementations together.
