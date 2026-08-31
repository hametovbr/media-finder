# Bilingual Web UI Specification

## Purpose

Define an accessible bilingual, bundled browser interface that manages the supported catalog-to-Acquisition workflow exclusively through the same-origin control API.

## Requirements

### Requirement: Manual metadata workflows
The built-in interface SHALL provide structured Manual movie and series creation, complete version-1 Manual JSON import, lossless editing of existing Manual items, and atomic episode CSV import for existing Manual series. The structured editor SHALL support localized titles, common normalized fields, seasons, episodes, and Season 00 specials. It SHALL submit only the existing browser control Manual operations and SHALL NOT create a presentation-owned metadata or persistence path.

When editing an existing Manual item, the interface SHALL preserve its immutable Manual external identifier, SHALL NOT permit its movie or series kind to change, SHALL preserve every normalized field not changed through the structured editor, and SHALL remove a season or episode only when the user deliberately removes that row. A non-Manual item SHALL NOT expose an actionable Manual editor.

#### Scenario: Create a structured Manual movie
- **WHEN** a user enters valid Manual movie fields and optionally selects a collection
- **THEN** the interface submits one complete version-1 Manual document through the control API and opens the resulting catalog item without creating an Acquisition

#### Scenario: Create a Manual series with specials
- **WHEN** a user enters a Manual series containing regular seasons and Season 00 episodes
- **THEN** the interface submits the hierarchy with its explicit season and episode numbers and presents the saved immutable revision

#### Scenario: Import a complete Manual document
- **WHEN** a user supplies a valid complete version-1 Manual JSON document
- **THEN** the interface validates and submits the complete document without dropping supported rich fields or rewriting a supplied valid Manual identity

#### Scenario: Confirm an existing Manual identity
- **WHEN** a Manual import or edit targets an existing Manual identity and the control API returns `confirmation_required` with a valid Manual confirmation token
- **THEN** the interface presents an explicit review step and submits that opaque token only after user confirmation

#### Scenario: Manual confirmation expires
- **WHEN** a Manual confirmation token is consumed, expired, evicted, or invalidated by restart
- **THEN** the interface presents localized safe feedback and requires the originating import or edit to be repeated without replaying the stale token

#### Scenario: Edit a rich Manual revision
- **WHEN** a user changes structured fields after importing a rich Manual document
- **THEN** the interface submits a complete document that applies the visible changes, preserves every unedited normalized field, keeps the existing identity and kind, and removes only deliberately deleted season or episode rows

#### Scenario: Reject editing a non-Manual item
- **WHEN** a user navigates to the edit route for an item whose provider is not Manual
- **THEN** the interface presents localized non-actionable feedback and does not submit a Manual mutation

#### Scenario: Import valid episode CSV
- **WHEN** a user submits a valid bounded episode CSV document for a Manual series
- **THEN** the interface applies all rows through one atomic control operation and presents the resulting revision

#### Scenario: Reject invalid episode CSV
- **WHEN** any row in an episode CSV document is invalid
- **THEN** the interface presents localized safe validation feedback and no partial episode update is shown or applied

### Requirement: Same-origin control client
The built-in interface SHALL bootstrap its browser session and execute its catalog, provider metadata, Manual metadata, release, destination, and Acquisition workflows exclusively through the same-origin `/api/control/v1` JSON contract. It SHALL send the session CSRF token and JSON media type on mutations, SHALL NOT call the processor `/api/v1` surface, and SHALL NOT receive a processor integration token, backend service, repository, database object, or concrete integration instance.

#### Scenario: Bootstrap the built-in client
- **WHEN** a browser opens the built-in interface without an existing valid session
- **THEN** the interface obtains its supported locales, selected locale preferences, and CSRF token from `/api/control/v1/session` while the signed session cookie remains HttpOnly

#### Scenario: Submit a protected mutation
- **WHEN** the user confirms provider metadata, Manual metadata, or Acquisition submission
- **THEN** the interface sends same-origin JSON with the current session CSRF token and the backend applies the existing control-contract behavior

#### Scenario: Inspect browser traffic
- **WHEN** the supported built-in workflows are exercised in a browser
- **THEN** no request targets `/api/v1` and no processor Bearer credential is present in browser state or traffic

### Requirement: Supported built-in workflow
The built-in interface SHALL expose catalog browsing, read-only collection filtering, media overview, metadata-provider search and explicit selection, Manual create, edit, JSON import, and episode CSV import, release search and explicit selection, live destination selection, and idempotent Acquisition submission. It SHALL NOT expose general collection or catalog-item archive, restore, or move controls; Acquisition history or reconciliation controls; integration diagnostics; Settings; or About. The omitted workflows SHALL remain available through their unchanged browser control API operations for future interfaces and later increments.

#### Scenario: Complete the supported path
- **WHEN** a user browses the catalog, selects provider metadata, chooses a release and current destination, and confirms submission
- **THEN** the interface completes the path through `/api/control/v1` and presents the resulting Acquisition state without requiring an omitted secondary workflow

#### Scenario: Complete a Manual path
- **WHEN** a user creates or imports valid Manual metadata and declines `Find release`
- **THEN** the interface saves and opens the Manual catalog item without creating an Acquisition

#### Scenario: Open an omitted secondary route
- **WHEN** a user navigates to a removed route for Settings, diagnostics, About, catalog mutation, or Acquisition reconciliation
- **THEN** the client presents localized not-found feedback and does not invoke a legacy HTML handler or mutate state

### Requirement: Responsive catalog shell
The UI SHALL provide a desktop-first responsive shell with read-only collection navigation, `Uncategorized`, an add-title action, and a poster-grid main view. Desktop navigation SHALL remain visible beside the catalog, while a mobile viewport SHALL expose the same navigation through a keyboard-operable dismissible drawer without horizontal page overflow.

#### Scenario: Browse a collection
- **WHEN** a user selects an existing collection
- **THEN** the main view shows its active media cards in a responsive poster grid

#### Scenario: Browse on a mobile viewport
- **WHEN** a user opens and closes catalog navigation on a supported mobile viewport
- **THEN** focus moves predictably, every supported navigation action remains available, and the document does not require horizontal scrolling

#### Scenario: Poster artwork is absent or cannot load
- **WHEN** a catalog item has no normalized poster artwork or its external image fails
- **THEN** its card retains a stable poster-shaped local placeholder without requesting a remote fallback asset

### Requirement: Informative media cards
Each media card SHALL show title, year, media type, metadata provider, and the latest Acquisition state as `pending`, `submitted`, or `failed` when an attempt exists. A `pending` card SHALL indicate that manual reconciliation may be required and SHALL NOT imply client download progress. Cards SHALL NOT display download progress for any state.

#### Scenario: Acquisition remains pending
- **WHEN** an item's latest acquisition is pending manual reconciliation
- **THEN** the card shows `pending` with a manual-reconciliation indication without inventing download progress or exposing a reconciliation control in the supported built-in interface

### Requirement: Media detail navigation
A media-item page SHALL present the saved normalized overview and a `Find release` action. The overview SHALL retain the localized display title, media type, metadata provider, and plot or localized no-plot state, and SHALL additionally present every available release year, original title, genre, and poster according to the rules below.

The interface SHALL trim the original title and each genre label for presentation, omit an original title or genre whose trimmed value is empty, and preserve the stored relative order of the remaining genres. It SHALL display an available original title even when it equals the localized display title, and SHALL omit absent optional values without rendering an empty metadata row.

The poster candidate SHALL be the first normalized artwork entry whose kind equals `poster` case-insensitively. The interface SHALL treat that poster as informative content, assign its complete untrusted module-normalized HTTP(S) URL unchanged, load it lazily with no referrer, and give it a localized accessible name that identifies the displayed work. The interface SHALL NOT construct, rewrite, origin-filter, proxy, or server-fetch the URL. A URL accepted by the normalized artwork contract MAY address a public, loopback, private-network, or userinfo-bearing origin; the direct request SHALL NOT be represented as private or origin-restricted. When poster artwork is absent or fails to load, the interface SHALL replace it with a stable poster-shaped local fallback carrying a localized unavailable-image name and SHALL NOT request a remote fallback asset.

The poster and metadata SHALL form one responsive detail composition that preserves all metadata and actions without horizontal page overflow at supported mobile widths. A Manual item SHALL additionally provide an edit action that opens its structured Manual editor. A provider-backed item SHALL NOT expose that action. The built-in interface SHALL NOT expose Acquisition-history views, and SHALL expose season and episode hierarchy only while creating or editing Manual metadata.

#### Scenario: Review a rich saved item
- **WHEN** a saved item has poster artwork, original title, release year, genres, and plot
- **THEN** the detail page displays the first case-insensitive poster artwork, the original title, year, every non-empty trimmed genre in stored order, and the plot alongside its existing identity context and actions

#### Scenario: Omit absent or whitespace-only detail values
- **WHEN** original title is absent or whitespace-only, release year is absent, genres are empty or whitespace-only, and poster artwork is absent
- **THEN** the detail page renders no empty original-title, year, or genre row and shows the localized local poster fallback without hiding the remaining overview or actions

#### Scenario: Load untrusted stored artwork directly
- **WHEN** the first normalized poster contains any complete HTTP(S) URL accepted by the current artwork contract
- **THEN** the page assigns that exact URL unchanged to a lazy informative image with no referrer and does not construct, rewrite, origin-filter, proxy, or server-fetch it

#### Scenario: Replace failed detail artwork locally
- **WHEN** the selected poster URL fails to load
- **THEN** the page replaces it with the localized informative local fallback without requesting a remote fallback or removing metadata and actions

#### Scenario: Browse rich detail on mobile
- **WHEN** a user opens a rich media-item page at a supported mobile width
- **THEN** the poster, metadata, `Find release`, and any permitted Manual edit action remain available without horizontal document scrolling

#### Scenario: Open a series
- **WHEN** a user opens a series card whose provider is not Manual
- **THEN** the detail page exposes its rich normalized overview and release-search action without an editable season hierarchy or Manual edit action

#### Scenario: Open a Manual series
- **WHEN** a user opens a Manual series
- **THEN** the detail page exposes its rich normalized overview, release-search action, and an edit action whose editor can represent the current seasons, episodes, and Season 00 specials

### Requirement: Explicit add workflow
Adding an item SHALL begin with an explicit choice between metadata-provider search and Manual entry or import. The provider path SHALL continue through provider-scoped result selection and any required similarity confirmation, save the catalog item, and only then offer an optional `Find release` action. Results from different metadata providers SHALL be grouped separately and SHALL NOT be automatically merged. The Manual path SHALL follow the Manual metadata workflow and SHALL NOT search or impersonate an external provider.

#### Scenario: Add without downloading
- **WHEN** a user confirms provider metadata and declines `Find release`
- **THEN** the catalog item is saved without creating an Acquisition

#### Scenario: Select one provider result
- **WHEN** providers return similar results
- **THEN** the UI identifies each provider and requires one explicit selection

#### Scenario: Metadata selection expires
- **WHEN** a metadata selection token is expired, consumed, evicted, or invalidated by restart
- **THEN** the interface displays localized safe feedback and returns the user to metadata search without replaying the stale selection

#### Scenario: Choose Manual entry
- **WHEN** a user selects the Manual option from the add workflow
- **THEN** the interface opens the Manual create/import route without issuing a provider search

### Requirement: Preview-rich metadata result selection
The built-in metadata-search interface SHALL render each provider result as a row containing its existing identity context, a poster or stable local poster fallback, its optional description as plain text, and a localized row-level `Select` action. It SHALL NOT require a radio selection or a separate footer save action. Activating a row action SHALL immediately invoke the existing metadata-selection mutation and continue to the same saved-item or similarity-confirmation outcome. Selection SHALL be globally single-flight across the result set: the initiating row SHALL indicate progress, every result action SHALL remain disabled until the request settles, and a recoverable failure SHALL re-enable the actions without replaying or duplicating the mutation.

Remote result posters SHALL use the complete module-produced URL unchanged, lazy loading, and a no-referrer policy. A missing or failed poster SHALL use the established local fallback without requesting a remote fallback asset. The result list SHALL remain keyboard operable, visibly focused, semantically announced, localized in English and Russian, and free of horizontal page overflow at supported mobile widths.

#### Scenario: Review enriched provider results
- **WHEN** metadata search returns results with poster and description previews
- **THEN** each provider-grouped row displays its preview as plain text and one localized `Select` action without a radio control or footer save action

#### Scenario: Show absent or failed previews
- **WHEN** a result has no description or its poster is absent or fails to load
- **THEN** the row remains selectable, omits the absent description without an empty interactive region, and retains a stable local poster fallback

#### Scenario: Load a direct provider poster safely
- **WHEN** a result has a valid complete poster URL
- **THEN** the browser requests that exact URL lazily with no referrer and the UI neither constructs nor rewrites it

#### Scenario: Select a result immediately
- **WHEN** the user activates a row's `Select` action once
- **THEN** the UI sends one existing selection mutation and continues to the same saved-item or required similarity-confirmation outcome without another confirmation click for ordinary selection

#### Scenario: Prevent parallel selections
- **WHEN** a selection request is pending and the user attempts to activate any result action again
- **THEN** only the original mutation exists, the initiating row shows pending state, and every result action remains disabled until the request settles

#### Scenario: Recover from a selection failure
- **WHEN** the selection request fails with a recoverable error
- **THEN** the UI presents localized semantic feedback and re-enables all result actions without automatically replaying the request

#### Scenario: Confirm a similar item
- **WHEN** selection returns a similarity-confirmation result with an opaque confirmation token
- **THEN** the UI presents the existing explicit review step and submits that returned token only after user confirmation

#### Scenario: Similarity confirmation expires
- **WHEN** the similarity-confirmation token is consumed, expired, evicted, or invalidated by restart
- **THEN** the UI presents localized safe feedback and returns to metadata search without replaying the stale token

#### Scenario: Select a result on a mobile keyboard workflow
- **WHEN** a keyboard-only user operates the result list at a supported mobile width
- **THEN** every row action is reachable with visible focus, status changes are semantically announced, and the page does not require horizontal scrolling

### Requirement: Explicit release submission UI
The release-search UI SHALL accept a free query and optional Prowlarr indexer identifiers, then require explicit selection of a release and a live qBittorrent destination. The sole environment-owned qBittorrent instance SHALL be selected implicitly and SHALL NOT be configurable through the UI.

#### Scenario: Search selected Prowlarr indexers
- **WHEN** a user supplies one or more valid Prowlarr indexer identifiers with a release query
- **THEN** the UI submits those identifiers through the existing browser control release-search operation and keeps release selection explicit

#### Scenario: Search all Prowlarr indexers
- **WHEN** a user submits a release query without indexer identifiers
- **THEN** the UI searches without an indexer restriction

#### Scenario: Submit selected release
- **WHEN** a user selects a release and current destination and confirms
- **THEN** the UI initiates one idempotent Acquisition tied to the current metadata revision and the environment-owned qBittorrent identity

#### Scenario: qBittorrent is unavailable
- **WHEN** the environment-owned qBittorrent instance cannot be constructed or validated, or its live destinations cannot be loaded
- **THEN** the release UI reports a localized safe diagnostic and does not offer stale persisted clients or an actionable submission control

#### Scenario: Archive and restore a download-client instance
- **WHEN** a caller attempts to archive or restore a download-client instance through a former UI route
- **THEN** the request is rejected because the environment-owned qBittorrent identity has no user-managed lifecycle

### Requirement: Localized and accessible interaction
All human-readable UI text SHALL be localizable in English and Russian. For an API or domain error, the UI SHALL select a localized human-readable message by its stable invariant machine error code. Machine error codes SHALL remain language-neutral, stable, and byte-for-byte unchanged across locales and SHALL never be translated. Critical flows SHALL support keyboard navigation, visible focus, associated labels, and semantic status feedback.

#### Scenario: Switch interface language
- **WHEN** a user selects Russian
- **THEN** subsequent UI pages use Russian localization while developer documentation and persisted provider identifiers remain unchanged

#### Scenario: Complete add flow by keyboard
- **WHEN** a keyboard-only user adds and confirms an item
- **THEN** every required control is reachable and the result is announced through semantic feedback

#### Scenario: Localize an error message
- **WHEN** the same stable machine error code is presented in English and Russian UI locales
- **THEN** the human-readable message uses the selected locale while the machine error code is identical in both responses and diagnostic context

#### Scenario: Unknown machine error code
- **WHEN** the UI receives an unrecognized stable machine error code
- **THEN** it displays a localized generic safe error message while retaining the unchanged code for diagnostics

### Requirement: External-auth trust and CSRF protection
The UI SHALL maintain no user-account database and SHALL rely on external reverse-proxy authentication when exposed beyond localhost. Mutating UI requests SHALL require a valid signed session and CSRF token. Session cookies SHALL be `HttpOnly`, `SameSite=Lax`, and configurable as `Secure` for HTTPS.

#### Scenario: Missing CSRF token
- **WHEN** a browser submits a mutating UI request without a valid CSRF token
- **THEN** the system rejects the request without applying changes

#### Scenario: HTTPS deployment
- **WHEN** the operator enables secure-cookie mode behind an HTTPS reverse proxy
- **THEN** the session cookie includes the `Secure` attribute

### Requirement: Independently buildable built-in interface
The bundled interface SHALL be delivered as a separately buildable package whose browser source consumes the deterministic public control OpenAPI contract and presentation libraries only. It SHALL NOT require database, persistence-model, domain-service, runtime-integration, metadata-provider, download-client, backend repository, or processor SDK imports. Its deterministic development mode SHALL render the supported built-in workflow, including Manual create, edit, import, confirmation, and validation states, English and Russian states, responsive layouts, and safe errors with typed fake HTTP responses and no database or external integration.

#### Scenario: Develop the interface in isolation
- **WHEN** a contributor starts the built-in UI development host without Media Finder storage or integration variables
- **THEN** the client renders deterministic catalog, provider metadata, Manual metadata, release, Acquisition, confirmation, validation-error, English, Russian, desktop, and mobile states using the same serialized control shapes used in production

#### Scenario: Violate the package boundary
- **WHEN** built-in UI source imports a prohibited backend, processor, persistence, SDK, or integration package
- **THEN** an automated architecture check rejects the build

#### Scenario: Control schema changes
- **WHEN** the checked-in control OpenAPI document changes without regenerating the built-in client's typed contract
- **THEN** deterministic frontend verification rejects the drift

### Requirement: Built-in interface compatibility
The built-in interface SHALL preserve GET navigation for `/`, `/add`, `/add/manual`, `/items/{item_id}`, `/items/{item_id}/edit`, and `/items/{item_id}/releases` as client routes with equivalent supported outcomes. Removed server-rendered form actions, fragment endpoints, and secondary HTML routes SHALL NOT remain as a parallel presentation path. Their removal SHALL NOT alter the backend control, processor, persistence, or integration semantics.

#### Scenario: Use an existing bookmark and form workflow
- **WHEN** a user upgrades across the built-in UI replacement boundary, opens a supported bookmark, or submits a formerly supported server-rendered form
- **THEN** the GET bookmark renders the corresponding client route, while the removed form submission is rejected without changing state and the supported operation remains available through `/api/control/v1`

#### Scenario: Use a supported bookmark
- **WHEN** a user opens a catalog, provider-add, Manual-add, item-detail, Manual-edit, or release-selection bookmark
- **THEN** the built-in client renders the corresponding supported route and obtains its state from the browser control API

#### Scenario: Submit a legacy form action
- **WHEN** a caller submits a removed Jinja or HTMX form or fragment route
- **THEN** the application rejects the unsupported route without invoking a second domain path or changing state

#### Scenario: Compare built-in and control behavior
- **WHEN** a supported built-in workflow and a direct browser control request perform the same catalog, provider metadata, Manual metadata, release, or Acquisition operation
- **THEN** both use the same browser control endpoint and produce the same state transition and invariant machine error code
