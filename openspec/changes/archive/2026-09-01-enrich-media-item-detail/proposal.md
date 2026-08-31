## Why

The saved media-item response already contains poster artwork, genres, release year, and original title, but the bundled detail page exposes only the year among those fields. Showing the persisted normalized values makes the page useful immediately after either provider-backed or Manual addition without introducing another metadata path.

## What Changes

- Extend the existing media-item detail presentation with the first normalized poster artwork, original title, release year, and ordered genres while retaining the current localized title, type, provider, plot, and actions.
- Render the stored poster URL unchanged as an informative, lazy, no-referrer image; use the existing local poster-shaped fallback when artwork is absent or fails, without adding an origin policy, proxy, server fetch, or remote fallback.
- Trim original-title and genre presentation values, omit whitespace-only optional text, and preserve the order of the remaining genre labels.
- Keep the richer page localized in English and Russian, accessible, and free of horizontal overflow at supported mobile widths.
- Preserve current loading and error behavior, `Find release`, Manual-only edit access, and the omission of season/episode hierarchy and Acquisition history.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `bilingual-web-ui`: Expand the existing media-detail requirement to define rich saved metadata, poster failure and direct-load behavior, optional-value handling, localization, accessibility, and responsive presentation.

## Impact

- Affects the bundled React `MediaDetailPage`, its English/Russian presentation strings, deterministic fixtures, unit/accessibility/browser coverage, and the canonical `bilingual-web-ui` specification.
- Reuses the existing `MediaItemDetail.metadata` control response and generated TypeScript types.
- Does not change module SDK or normalized schemas, provider implementations, core, persistence, migrations, `/api/control/v1`, OpenAPI, runtime composition, deployment, or compatibility boundaries.
