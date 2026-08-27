## Context

See `proposal.md` for the motivation. The current bundled interface is a React/Vite single-page application in `packages/builtin-ui/web`; FastAPI serves its compiled assets and exposes the same-origin `/api/control/v1` browser boundary. The checked-in control OpenAPI document already contains Manual import, confirmation, edit, and episode-CSV operations, and `MediaItemDetail` already carries the normalized fields needed to reconstruct a complete Manual document. The missing work is therefore presentation integration, not a new domain path.

The browser package may depend only on control contracts and presentation libraries. It cannot import backend validation models, core services, repositories, persistence, or integration modules. The existing session endpoint remains the source of the metadata locale and CSRF token. Confirmation tokens are opaque, short-lived server state and must not become durable browser state. Module attribution remains owned by module declarations and exposed through the existing control resource; the built-in interface does not need an About/Credits view.

The OpenSpec context still names the removed Jinja2/HTMX implementation. This change updates that repository guidance, but it does not restore server-rendered forms or make templates part of the runtime again.

## Goals / Non-Goals

**Goals:**

- Extend the existing React package and typed same-origin control client with a complete Manual workflow while preserving the current package graph and security boundary.
- Make structured create and edit practical for common metadata, and make complete schema-v1 JSON the lossless escape hatch for every supported Manual field.
- Preserve imported rich metadata during structured edits, including fields that the structured editor does not expose.
- Provide deterministic English/Russian, validation, confirmation, desktop, and mobile states in the isolated UI development environment.
- Reconcile repository guidance with the React/Vite implementation and make the restored workflow testable at component, browser, composed-server, and production-asset boundaries.

**Non-Goals:**

- Changing the browser control API, processor API, OpenAPI schema, normalized metadata schema, persistence model, module SDK, or Manual business rules.
- Adding another validation engine, form framework, state library, server route family, process, service, container, database migration, or integration configuration.
- Adding About/Credits, Settings, diagnostics, catalog mutation, or Acquisition history and reconciliation screens.
- Reintroducing Jinja2/HTMX handlers, templates, fragments, or compatibility form actions.
- Turning the built-in UI into an owner of metadata normalization, identity generation, duplicate detection, CSV parsing, or confirmation-token validity.

## Decisions

### 1. Extend the existing browser package at the package rung

The implementation will add routes, components, pure document-mapping helpers, client methods, translations, mocks, and tests inside `packages/builtin-ui/web`. FastAPI continues to serve the compiled SPA and remains the only composition root. The core Manual service remains the owner of identity, normalization, duplicate detection, revisions, and atomic episode import.

This is the lowest sufficient complexity rung. No new runtime component is justified: the browser, control gateway, core Manual path, storage, and static host already exist. A separate Manual package, browser-side domain service, server-rendered sub-application, or auxiliary process would duplicate an existing owner and violate the package boundary.

Module and secret boundaries do not change. The Manual module remains a statically registered server dependency. The browser receives neither module instances nor environment values, and no new secret or environment declaration is introduced. Existing CSRF and signed-session behavior continues to protect mutations.

### 2. Use explicit client routes and conditional navigation

The router will add:

- `/add/manual` for structured create and complete JSON import;
- `/items/:itemId/edit` for structured editing of an existing Manual item and episode CSV import.

The existing `/add` page will present provider search and Manual entry/import as explicit alternatives. The media detail page will show `Edit` only when `provider_key` is `manual`. Direct navigation to the edit route will still fetch the item and reject a non-Manual provider without rendering an actionable form. Successful mutations will invalidate the relevant catalog and media-detail queries and navigate to the resulting detail route. They will not create an Acquisition or automatically start release search.

Dedicated routes make refresh, back/forward navigation, testing, and bookmarks predictable. A modal-only workflow was rejected because it would hide state in the catalog/detail page and make large nested series forms and import error recovery harder. Restoring the former HTML route implementation was rejected because it would create a second presentation and mutation path.

No `/about` route or navigation item will be added. `/api/control/v1/about` and generated types remain unchanged for external interfaces.

### 3. Add narrow typed operations and allowlist confirmation details

The current control client will gain typed methods corresponding exactly to the generated contract:

- import a `ManualImportRequest` through `POST /v1/manual-imports`;
- confirm an import or edit through `POST /v1/manual-imports/{token}/confirm`;
- replace Manual metadata through `PUT /v1/media-items/{itemId}/manual-metadata`;
- import an `EpisodeImportRequest` through `POST /v1/media-items/{itemId}/episode-imports`.

The common mutation helper will continue to attach the current CSRF token and JSON media type. The client error type will expose optional Manual confirmation data only when the invariant error code is `confirmation_required` and the response details contain both a string `confirmation_token` and `kind: "manual"`. It will discard arbitrary error details and will never interpolate a token into diagnostics, rendered raw errors, URLs, analytics, or logs.

Keeping this extraction in the shared HTTP boundary gives the create and edit screens one security-reviewed representation. Passing the entire untyped `details` object into components was rejected because future server details could contain data that is unsafe or irrelevant to render. Creating a new response DTO or endpoint was rejected because the existing error envelope is sufficient.

### 4. Keep one complete Manual document as editor state

The editor state will be the generated `ManualDocumentV1` shape, manipulated through pure presentation-layer helpers. It will not introduce a second reduced persistence model. Stable client-only row keys may accompany seasons and episodes for rendering, but those keys will be stripped before submission.

For structured creation, the user chooses movie or series and enters the active-locale title plus common normalized fields: original title, year, plot, release date, runtime minutes, genres, tags, countries, and studios. A series editor additionally exposes season number, season title and plot, and episode number, title, plot, air date, runtime minutes, and ordering. Season number `0` is accepted for specials. An optional collection identifier remains request context rather than part of the Manual document. Structured creation omits `external_id` so the existing Manual owner generates it.

Provider identifiers, ratings, people, artwork, and titles in locales other than the active metadata locale remain available through complete JSON import. They are not duplicated as partially capable structured controls in this increment. This is an intentional subtraction: the JSON path already represents these fields exactly, while shallow structured widgets would increase validation and accessibility surface without adding contract coverage.

For edit, a pure adapter will construct a complete document from `MediaItemDetail`: it copies the immutable `external_id` and `kind`, uses the session metadata locale, and carries every normalized metadata field into editor state. The kind and external identifier will be visible as locked identity rather than editable inputs. Structured changes will update only their corresponding fields on the complete document. Unexposed fields and non-active-locale titles remain unchanged. Explicit removal of a season or episode row removes it from the submitted document; merely leaving a field untouched does not.

A smaller form-specific request object was rejected because reconstructing the request from only rendered fields would silently erase rich imported metadata. Browser imports of backend Python models were rejected by the package boundary. The generated TypeScript contract is the sole transport type; server validation remains authoritative.

### 5. Treat JSON import as a complete, server-validated contract path

The Manual-add page will offer structured entry and complete JSON import as two modes. JSON can be pasted or loaded from a local file using browser file APIs; file contents remain in component memory. The client will perform syntax parsing, require a JSON object, and give immediate feedback for a missing or unsupported `schema_version`. It will then submit the parsed document through the typed control operation and render invariant server validation errors safely.

The browser will not implement a second copy of the Pydantic or checked JSON Schema validator. Duplicated semantic validation would drift from the authoritative control contract. Focused client checks improve basic usability; the server owns field bounds, enum values, UUID rules, hierarchy uniqueness, identity behavior, and normalization.

### 6. Keep episode CSV raw and atomic

Episode CSV import will appear only on the edit route for an existing Manual series. The user may paste CSV or load a `.csv` file. The client will reject an empty document and a UTF-8 payload larger than the contract's one-mebibyte limit, then submit the raw text as `EpisodeImportRequest`. It will not parse, preview as authoritative rows, or apply client-side partial changes. The server continues to validate the whole document and either creates one new immutable revision or applies nothing.

Client-side CSV parsing was rejected because quoting, headers, duplicate keys, and field validation already have a single tested backend owner. Sending individual episode mutations was rejected because it would break the existing atomicity guarantee.

### 7. Keep confirmation ephemeral and recoverable

When an import or edit returns an allowlisted Manual confirmation token, the originating page will retain the source document in memory and show an explicit localized confirmation dialog summarizing that an existing Manual identity will be revised. Only the confirmation action sends the opaque token. Cancellation clears the token without mutation.

The token will not be stored in local storage, session storage, a query string, router state intended for persistence, or a test snapshot. If confirmation returns an expired, consumed, evicted, restarted, or otherwise invalid-token error, the page clears the token, retains the source inputs, and instructs the user to resubmit the originating import or edit to obtain a new decision. The client will not retry confirmation automatically.

Durable token storage and transparent replay were rejected because confirmation state is intentionally short-lived and single-use. Automatically converting `confirmation_required` into a hidden second request was rejected because the contract requires explicit user intent.

### 8. Reuse the current presentation stack and make dynamic forms accessible

The implementation will use existing Mantine controls, TanStack Query mutation/query primitives, React Router, i18next, and the existing notification/error patterns. It will not add a form, schema-validation, CSV, or state-management dependency.

Dynamic season and episode groups will use semantic grouping and stable labels that include their position or explicit number. Add and remove controls will be keyboard reachable, destructive row removal will require deliberate activation, validation summaries will link or focus the first invalid control where practical, and asynchronous success/error/confirmation states will use the existing accessible alert/dialog primitives. Mobile layouts will stack nested controls without horizontal overflow. All new visible copy and invariant error mappings will be added to both English and Russian catalogs.

A generic JSON-schema-generated form was rejected because it would add runtime machinery, produce a weaker nested editing experience, and couple presentation to schema-generation behavior. A new shared design-system abstraction was rejected because the existing controls are sufficient.

### 9. Extend deterministic mocks and verify each existing boundary

MSW handlers will add deterministic Manual movie, rich Manual series, duplicate-confirmation, invalid-document, expired-confirmation, valid-CSV, and invalid-CSV states using generated control shapes. They will model revision replacement and atomic failure sufficiently for browser behavior tests, without reproducing backend normalization logic.

Implementation will follow test-driven slices:

- pure mapping tests prove that rich unexposed fields and immutable identity survive structured edits;
- control-client tests prove endpoints, CSRF, JSON bodies, confirmation allowlisting, and safe error handling;
- component tests prove structured create, JSON import, explicit confirmation, edit gating, deliberate row removal, CSV states, localization, and keyboard behavior;
- Playwright tests prove bookmarked routes and representative desktop/mobile workflows against MSW;
- composed-server and static-host checks prove SPA fallback, control-only mutation traffic, rejection of legacy form routes, deterministic assets, and packaged-wheel behavior.

Backend Manual conformance tests remain the authority for identity, revision, schema, and CSV atomicity. New frontend tests will reference those approved requirements rather than duplicate the algorithms. Generated OpenAPI drift and package-boundary checks remain mandatory even though no contract change is expected.

### 10. Reconcile documentation without creating a compatibility promise

`openspec/config.yaml` will describe React/Vite rather than Jinja2/HTMX. Contributor, browser-control, implementation-plan, operations, and clean-checkout instructions that currently omit Manual UI support or reference removed templates, Settings, or obsolete commands will be updated to match the shipped package and supported routes. Historical archived OpenSpec changes will not be rewritten.

Documentation will continue to state that legacy HTML mutations are unsupported. Naming the new client bookmarks does not reintroduce compatibility for removed POST or fragment routes.

## Risks / Trade-offs

- [A structured edit could erase rich imported fields] -> Use the complete generated document as state, centralize detail-to-document mapping, and require a rich fixture regression test that edits one visible field while comparing every untouched field.
- [The browser may accidentally trust or expose arbitrary error details] -> Extract only the two allowlisted Manual confirmation fields at the HTTP boundary and test malformed, unrelated, and missing details.
- [Large nested series forms may be difficult on mobile or with assistive technology] -> Use semantic groups, stable row keys, explicit add/remove actions, responsive stacking, focus-aware validation, and desktop/mobile accessibility checks.
- [Frontend validation may disagree with authoritative Manual rules] -> Limit client checks to syntax and immediate size/shape feedback; render stable server codes and keep semantic validation in the existing control/core path.
- [A stale confirmation token can produce a confusing retry loop] -> Clear failed tokens, retain source input, require a fresh originating submission, and never auto-replay.
- [Mock behavior may drift into a second Manual implementation] -> Keep fixtures deterministic and transition-oriented; retain real gateway/control conformance as the domain authority.
- [Generated or packaged assets may omit new routes or translations] -> Run locale parity, production build, generated-asset drift, SPA fallback, wheel-isolation, composed-server, and production-image checks on the exact candidate.
- [The structured editor intentionally omits some rich fields] -> Preserve those fields losslessly during edit and support them through the complete JSON import path; do not present partial controls that imply full editing capability.

## Migration Plan

1. Add tests and implementation in focused client, mapping, create/import, edit/CSV, routing, and browser slices while retaining the existing control contract.
2. Regenerate only deterministic built-in UI assets required by the normal frontend build; the checked control OpenAPI document and generated client types should remain unchanged and their drift checks must confirm that assumption.
3. Update current repository guidance and canonical specifications through the normal OpenSpec synchronization and archive phases.
4. Build and verify the same application image and isolated workspace wheels used for delivery. No database, data, module, secret, environment, or operator migration is required.
5. Deploy the immutable image normally. Existing Manual items remain compatible because requests use the unchanged version-1 document and revision behavior.

Rollback is deployment of the previous immutable application image. No data down-migration is required: the restored interface only invokes pre-existing operations and does not introduce a new stored representation. Manual revisions created through the interface remain valid catalog history after rollback and remain accessible through the unchanged control API.
