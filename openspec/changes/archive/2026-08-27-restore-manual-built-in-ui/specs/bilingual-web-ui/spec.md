## ADDED Requirements

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

## MODIFIED Requirements

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

### Requirement: Media detail navigation
A media-item page SHALL provide the normalized overview and a `Find release` action. A Manual item SHALL additionally provide an edit action that opens its structured Manual editor. A provider-backed item SHALL NOT expose that action. The built-in interface SHALL NOT expose Acquisition-history views, and SHALL expose season and episode hierarchy only while creating or editing Manual metadata.

#### Scenario: Open a series
- **WHEN** a user opens a series card whose provider is not Manual
- **THEN** the detail page exposes its normalized overview and release-search action without an editable season hierarchy or Manual edit action

#### Scenario: Open a Manual series
- **WHEN** a user opens a Manual series
- **THEN** the detail page exposes its normalized overview, release-search action, and an edit action whose editor can represent the current seasons, episodes, and Season 00 specials

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
