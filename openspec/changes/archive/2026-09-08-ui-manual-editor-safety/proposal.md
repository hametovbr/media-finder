## Why

The Manual editor rewrites comma-separated input while typing, permits competing save/import actions, and can discard unsaved fields when importing CSV or leaving the page. Stage 4 of MF-UIUX-2026-09 addresses these source-verified gaps after the preceding recovery and dependency changes were delivered.

## What Changes

- Preserve raw genres, tags, countries and studios text until request normalization, including across mode changes, secondary-field disclosure and UI-language changes; retain unedited rich metadata and immutable edit identity/kind.
- Coordinate structured save, JSON import, episode CSV import, duplicate confirmation and local file reads within each Manual page. Capture one operation snapshot, prevent duplicate or competing mutations, retain drafts after failure and prevent stale file results from overwriting newer input.
- Require explicit confirmation before row removal or a new series-to-movie change that drops hierarchy; protect dirty navigation with a stay/leave choice.
- Block CSV submission while structured fields differ from the saved revision. Before submitting one mode with another unsaved draft, explain what successful navigation would discard and require explicit consent; do not silently compose a save and CSV transaction.
- Add a small secondary-field disclosure, hierarchy counts and plain-language CSV consequences, with English/Russian, keyboard, focus and mobile acceptance.
- Stabilize the existing Manual confirmation test by waiting for visible state instead of asserting visibility immediately after DOM discovery. Preserve production animation.

These are additions to built-in UI behavior only. No product capability is removed; existing Manual creation, complete JSON import, editing and atomic episode CSV remain available. No backend/API/schema changes, durable drafts/autosave, general hierarchy redesign, new dependencies, workflow changes or stable release are included.

## Capabilities

### New Capabilities

None; the existing built-in UI capability owns these interactions.

### Modified Capabilities

- `bilingual-web-ui`: non-destructive Manual input, per-page operation exclusion, explicit destructive/draft transitions, saved-revision CSV coordination and accessible secondary-field disclosure.

## Impact

- Existing owners: `packages/builtin-ui/web/src/manual/manual-editor.tsx`, `manual-document.ts`, `manual-add-page.tsx` and `manual-edit-page.tsx`; corresponding tests; EN/RU locale catalogs; existing `web/e2e/shell.spec.ts` and screenshot attachments. Generated static assets are rebuilt only during implementation.
- Existing router hooks and control-client operations remain the integration seams. The wire DTOs, control client signatures, backend revision writer, module ownership, retention and acquisition semantics remain unchanged.
- Evidence baseline: main `3e47f352f0830b0bd5fd9f00f6a52a35b5d2ab47`, tree `d738e6a0b14f473020045f9946786578946bc84e`. The user approved the independently reviewed `media-finder-stage4-context.md` handoff on 2026-09-08. Its RQ-001 through RQ-007 map to the design/tasks; this proposal remains subject to separate implementation approval.
- Current verification limitation: the primary focused Manual run passed 22 tests; a Luna full-suite run passed 117/118 and observed a dialog at opacity 0 in the immediate visibility assertion. No new browser acceptance or production implementation is claimed.
