## 1. Release-Flow Conformance Tests

- [x] 1.1 Add a focused failing control-client test proving release searches serialize supplied Prowlarr indexer identifiers and serialize an empty list when no filter is supplied; record the expected RED result.
- [x] 1.2 Add focused failing release-page tests for valid optional indexer identifiers, locally rejected malformed identifiers, and unchanged explicit release selection; record the expected RED result.
- [x] 1.3 Add a focused failing release-page test proving a failed live-destination lookup renders localized safe feedback, exposes no stale destination, and disables Acquisition submission; record the expected RED result.

## 2. Minimal Presentation-Layer Reconciliation

- [x] 2.1 Extend the typed control-client release-search call to accept indexer identifiers through the existing generated `ReleaseSearchRequest.indexer_ids` field without changing the OpenAPI contract.
- [x] 2.2 Add the optional indexer-identifier control and deterministic validation to the release page, keeping an unfiltered search as the default.
- [x] 2.3 Render normalized destination-query failures as localized semantic feedback, clear stale destination state, and keep submission unavailable until fresh destinations load.
- [x] 2.4 Add complete English and Russian localization entries for the new filter guidance, validation feedback, and known download-client failure code while preserving generic safe fallback behavior.

## 3. Regression and Specification Handoff

- [x] 3.1 Run the focused control-client, release-page, localization, and accessibility tests and resolve all failures.
- [x] 3.2 Run frontend format, lint, strict type-check, unit tests, accessibility checks, generated-contract drift, and clean production build; verify generated packaged assets are current.
- [x] 3.3 Run `pnpm spec:validate` and the relevant Python static-host, architecture, control OpenAPI, and packaged-wheel checks; report any unavailable gate as `not run` or `blocked`.
- [x] 3.4 Verify the apply handoff identifies the canonical `bilingual-web-ui` Purpose correction as synchronization/archive work and does not edit canonical specifications during apply.
