## Why

The canonical specifications currently disagree about whether the bundled React interface supports Manual metadata workflows, and repository guidance still describes parts of the removed Jinja2/HTMX presentation. The browser control API already exposes the complete Manual contract, so the supported UI and its specifications need to be reconciled without adding a second business path or restoring the legacy server-rendered implementation.

## What Changes

- Restore Manual movie and series creation, complete schema-v1 JSON import, lossless Manual editing, and atomic episode CSV import in the bundled React interface through the existing `/api/control/v1` operations.
- Add bookmarkable `/add/manual` and `/items/{item_id}/edit` client routes while keeping the provider-search add flow, catalog, media detail, release selection, and Acquisition behavior unchanged.
- Preserve Manual identity and revision rules: existing identities require explicit opaque confirmation, `external_id` and media kind remain immutable, rich fields not changed by the structured editor remain intact, and removed season or episode rows are removed deliberately.
- Keep About/Credits absent from the bundled interface. Preserve `/api/control/v1/about`, module attribution declarations, and external-interface compatibility without adding a built-in About route.
- Keep removed Jinja2/HTMX form, fragment, and mutation routes unsupported; all restored browser behavior uses the same-origin control API and existing CSRF/session boundary.
- Reconcile deployment and repository guidance with the current React/Vite static-asset package and remove stale Jinja2/HTMX, omitted-Manual, Settings-page, and obsolete development-command descriptions.
- Do not change the browser control or processor wire contracts, normalized metadata schema, persistence, module contracts, integration environment, runtime topology, or container count.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `bilingual-web-ui`: Add the complete Manual create, edit, JSON import, and episode CSV workflows to the supported bundled interface while continuing to omit About/Credits and the other explicitly deferred secondary workflows.
- `catalog-and-metadata`: Replace the stale About/Credits-view attribution scenario with durable module and browser-control attribution availability while preserving all Manual identity, revision, and rich-metadata behavior.
- `deployment-and-delivery`: Describe the built-in UI package as React/Vite browser source plus deterministic localized static assets rather than Jinja templates.

## Impact

- Extends `packages/builtin-ui/web` with Manual routes, typed control-client methods, safe confirmation-detail handling, localized fixtures, components, and focused Vitest/Playwright/accessibility coverage.
- Reuses the checked-in `/api/control/v1` OpenAPI document and the existing Manual endpoints; no public DTO or endpoint change is expected.
- Updates composed browser, security, control-parity, generated-asset, isolated-wheel, and production-image checks for the restored routes without reviving a second presentation or domain path.
- Updates `openspec/config.yaml` and English developer/operator documentation so later OpenSpec artifacts and clean-checkout instructions reflect the shipped React/Vite architecture and supported Manual workflow.
- Adds no runtime dependency, process, service, database migration, secret, environment variable, or compatibility shim. Rollback remains deployment of the previous immutable application image.
