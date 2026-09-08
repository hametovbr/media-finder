## Why

The built-in UI can leave users without actionable feedback when session bootstrap, metadata-provider loading, searches or language changes fail. Empty searches also have no distinct outcome, so a mobile-only user cannot reliably distinguish a failed request from an empty result or recover without losing context.

## What Changes

- Present localized session-bootstrap failure and explicit retry before the application shell is available.
- Handle metadata-provider loading failures with explicit retry and no actionable provider search until recovery.
- Distinguish initial, pending, successful non-empty, successful empty and failed metadata/release searches; preserve input and provide deliberate retry.
- Prevent old search results or late responses from being mistaken for the current submitted query.
- Report failed interface-language changes while retaining the last confirmed language and current page state.
- Provide semantic status/error feedback and keyboard-operable recovery in English and Russian.
- Product boundary additions/removals: none. No new routes, API operations, persistence, integrations, background recovery, Acquisition retry semantics or Manual-editor changes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `bilingual-web-ui`: explicit failure, empty-result and user-controlled recovery behavior for bootstrap, provider discovery, search and language preference changes.

## Impact

Affected source: `packages/builtin-ui/web/src/api/control-provider.tsx`, `main.tsx`, `app-router.tsx`, metadata/release pages, locale catalogs and their tests/fixtures. Regenerate packaged static assets through `pnpm ui:build` during implementation. Existing control-client operations and generated wire contracts remain unchanged; no dependency or database changes are needed.

This implements roadmap MF-UIUX-2026-09 stage 3 (A01-A03). Planning is based on source evidence at `b137f8b2be756e2d657301270d22624f3dbf35a1`; browser reproduction is not yet established. Local frontend build/unit checks work; browser and visual verification remain explicit delivery gates rather than assumed passes.
