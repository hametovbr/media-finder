## Why

The archived built-in Web UI replacement left the canonical capability with a stale server-rendered purpose, transitional wording, and two release-flow statements that are not fully demonstrated by the shipped client. The specification must describe the durable SPA boundary precisely, while the implementation and tests must continue to satisfy already-approved release filtering and safe download-client failure behavior rather than silently weakening those guarantees.

## What Changes

- Replace the stale server-rendered capability purpose with the durable definition of the bundled, API-driven browser interface during specification synchronization.
- Recast the “initial replacement” wording as the currently supported built-in workflow without expanding the exposed product surface.
- Define the existing Prowlarr filter promise precisely as optional indexer-ID filtering through the current `ReleaseSearchRequest.indexer_ids` control-contract field, and expose that filter in the release UI.
- Make unavailable or failed live-destination lookup produce localized safe feedback instead of an inert release screen.
- Clarify the combined upgrade-compatibility scenario while preserving focused checks for supported SPA bookmarks, rejection of removed legacy mutations, and browser/control parity.
- Add focused conformance tests for every reconciled statement and retain the existing package, process, API, security, persistence, and integration boundaries.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `bilingual-web-ui`: Replace transitional replacement-era language with the durable SPA contract, make optional indexer-ID filtering explicit, and make live-destination failure feedback directly testable.

## Impact

- Updates the `bilingual-web-ui` canonical purpose during specification synchronization and its normative requirements through an OpenSpec delta.
- Changes only the presentation layer under `packages/builtin-ui/web` and its focused tests; the minimal Python static host remains unchanged.
- Uses the existing deterministic `/api/control/v1` OpenAPI contract. No control API, processor API, module contract, schema, persistence, secret, environment, package-owner, process, or deployment change is introduced.
