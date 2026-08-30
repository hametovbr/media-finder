## Why

Metadata-provider search results currently lack enough context to distinguish similar titles, and the radio-selection-plus-footer-action interaction adds an unnecessary second step. The product is still pre-public with one bundled UI and no compatibility-bound external consumers, so the existing contracts can be updated directly before release.

## What Changes

- Enrich the existing metadata search result with an optional plain-text description and an optional complete poster URL produced by the metadata-provider module.
- Make the TMDB module map a valid TMDB `poster_path` to its complete `image.tmdb.org` URL while treating missing or invalid preview data as an absent preview rather than dropping the search result. Other providers remain free to construct poster URLs according to their own rules.
- Pass the module-produced preview fields unchanged through core and the existing `/api/control/v1` metadata-search response; core, control, and UI do not construct, rewrite, or branch on provider-specific poster URLs.
- **BREAKING** Update the current module SDK v1 schema and browser-control v1 schema in place, together with conformance fixtures, deterministic OpenAPI, and the generated bundled-UI client. No compatibility shim, parallel capability, or API v2 is introduced because there are no released consumers to preserve.
- Replace radio selection and the footer save action with a localized row-level `Select` action. Activating it immediately runs the existing selection mutation and continues to the same saved-item outcome, including the existing similarity-confirmation step when required.
- Keep selection globally single-flight: the initiating row shows progress, all result actions are disabled until the request settles, and a recoverable failure re-enables them without sending a second request.
- Render direct provider poster images lazily and without a referrer, retaining the established local poster fallback for missing or failed images and preserving accessible keyboard, focus, semantic-feedback, bilingual, and responsive behavior.
- Correct the bundled client at the affected seam so a similarity-confirmation response uses its returned opaque confirmation token and preserves the existing expired-token recovery behavior.
- Preserve provider grouping and identity, exact-duplicate handling, Manual workflows, catalog persistence, and the post-save `Find release` choice.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `module-contracts-and-retention`: Extend the existing metadata-provider search-result DTO and v1 serialized contract with optional provider-owned preview fields, including the rule that only the module constructs the complete poster URL.
- `catalog-and-metadata`: Define TMDB search-preview mapping and graceful absence for missing or invalid description/poster inputs without changing provider identity or persisted metadata semantics.
- `browser-control-api`: Enrich the existing metadata-search result representation in place and preserve request security, ephemeral selection state, and selection/confirmation behavior.
- `bilingual-web-ui`: Replace the two-step result chooser with accessible poster-and-description rows whose local action immediately invokes the existing single-flight selection flow.

## Impact

Affected areas are the public module SDK DTO/schema and conformance fixtures; the TMDB module and its tests; core metadata-search validation and ephemeral caching; browser-control DTOs, OpenAPI snapshot, gateway/HTTP conformance and security tests; and the bundled UI's generated client, deterministic fixtures, selection screen, localization, unit/accessibility, responsive, and browser tests. No database schema, migration, stored data, deployment topology, runtime module registration, new service, image proxy/cache, or additional persistence path is introduced.
