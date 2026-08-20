## ADDED Requirements

### Requirement: Same-origin control client
The built-in interface SHALL bootstrap its browser session and execute its catalog, metadata, release, destination, and Acquisition workflows exclusively through the same-origin `/api/control/v1` JSON contract. It SHALL send the session CSRF token and JSON media type on mutations, SHALL NOT call the processor `/api/v1` surface, and SHALL NOT receive a processor integration token, backend service, repository, database object, or concrete integration instance.

#### Scenario: Bootstrap the built-in client
- **WHEN** a browser opens the built-in interface without an existing valid session
- **THEN** the interface obtains its supported locales, selected locale preferences, and CSRF token from `/api/control/v1/session` while the signed session cookie remains HttpOnly

#### Scenario: Submit a protected mutation
- **WHEN** the user confirms metadata selection or Acquisition submission
- **THEN** the interface sends same-origin JSON with the current session CSRF token and the backend applies the existing control-contract behavior

#### Scenario: Inspect browser traffic
- **WHEN** the critical built-in workflow is exercised in a browser
- **THEN** no request targets `/api/v1` and no processor Bearer credential is present in browser state or traffic

### Requirement: Initial replacement workflow
The initial replacement interface SHALL expose catalog browsing, read-only collection filtering, media overview, metadata-provider search and explicit selection, release search and explicit selection, live destination selection, and idempotent Acquisition submission. It SHALL NOT expose Manual create, edit, import, or episode CSV controls; collection or media-item mutation controls; Acquisition history or reconciliation controls; integration diagnostics; Settings; or About during this initial release. The omitted workflows SHALL remain available through their unchanged browser control API operations for future interfaces and later increments.

#### Scenario: Complete the supported path
- **WHEN** a user browses the catalog, selects provider metadata, chooses a release and current destination, and confirms submission
- **THEN** the interface completes the path through `/api/control/v1` and presents the resulting Acquisition state without requiring an omitted secondary workflow

#### Scenario: Open an omitted secondary route
- **WHEN** a user navigates to a legacy route for Manual editing, Settings, diagnostics, About, or Acquisition reconciliation
- **THEN** the client presents localized not-found feedback and does not invoke a legacy HTML handler or mutate state

## MODIFIED Requirements

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
- **THEN** the card shows `pending` with a manual-reconciliation indication without inventing download progress or exposing a reconciliation control in the initial replacement interface

### Requirement: Media detail navigation
A media-item page SHALL provide the normalized overview and a `Find release` action. The initial replacement interface SHALL NOT expose season and episode hierarchy or Acquisition-history views.

#### Scenario: Open a series
- **WHEN** a user opens a series card
- **THEN** the detail page exposes its normalized overview and release-search action without claiming that omitted season, episode, or Acquisition-history views are available

### Requirement: Explicit add workflow
Adding an item SHALL begin with metadata-provider search, continue through explicit provider-scoped result selection and any required similarity confirmation, save the catalog item, and only then offer an optional `Find release` action. Results from different metadata providers SHALL be grouped separately and SHALL NOT be automatically merged. The initial replacement interface SHALL NOT expose Manual entry or import.

#### Scenario: Add without downloading
- **WHEN** a user confirms provider metadata and declines `Find release`
- **THEN** the catalog item is saved without creating an Acquisition

#### Scenario: Select one provider result
- **WHEN** providers return similar results
- **THEN** the UI identifies each provider and requires one explicit selection

#### Scenario: Metadata selection expires
- **WHEN** a metadata selection token is expired, consumed, evicted, or invalidated by restart
- **THEN** the interface displays localized safe feedback and returns the user to metadata search without replaying the stale selection

### Requirement: Independently buildable built-in interface
The bundled interface SHALL be delivered as a separately buildable package whose browser source consumes the deterministic public control OpenAPI contract and presentation libraries only. It SHALL NOT require database, persistence-model, domain-service, runtime-integration, metadata-provider, download-client, backend repository, or processor SDK imports. Its deterministic development mode SHALL render the initial replacement workflow, English and Russian states, responsive layouts, and safe errors with typed fake HTTP responses and no database or external integration.

#### Scenario: Develop the interface in isolation
- **WHEN** a contributor starts the built-in UI development host without Media Finder storage or integration variables
- **THEN** the client renders deterministic catalog, metadata, release, Acquisition, error, English, Russian, desktop, and mobile states using the same serialized control shapes used in production

#### Scenario: Violate the package boundary
- **WHEN** built-in UI source imports a prohibited backend, processor, persistence, SDK, or integration package
- **THEN** an automated architecture check rejects the build

#### Scenario: Control schema changes
- **WHEN** the checked-in control OpenAPI document changes without regenerating the built-in client's typed contract
- **THEN** deterministic frontend verification rejects the drift

### Requirement: Built-in interface compatibility
The replacement interface SHALL preserve GET navigation for `/`, `/add`, `/items/{item_id}`, and `/items/{item_id}/releases` as client routes with equivalent supported outcomes. Legacy server-rendered form actions, fragment endpoints, and secondary HTML routes SHALL NOT remain as a parallel presentation path. Removing them SHALL NOT alter the backend control, processor, persistence, or integration semantics.

#### Scenario: Use an existing bookmark and form workflow
- **WHEN** a user upgrades with the built-in UI enabled and opens a supported catalog, add, item-detail, or release-selection bookmark or submits a previously supported legacy HTML form
- **THEN** the GET bookmark renders the corresponding client route, while the legacy form submission is rejected without changing state and the supported operation remains available through `/api/control/v1`

#### Scenario: Use a supported bookmark
- **WHEN** a user opens a catalog, add, item-detail, or release-selection bookmark after upgrading
- **THEN** the built-in client renders the corresponding supported route and obtains its state from the browser control API

#### Scenario: Submit a legacy form action
- **WHEN** a caller submits a removed Jinja or HTMX form or fragment route
- **THEN** the application rejects the unsupported route without invoking a second domain path or changing state

#### Scenario: Compare built-in and control behavior
- **WHEN** a supported built-in workflow and a direct browser control request perform the same catalog, metadata, release, or Acquisition operation
- **THEN** both use the same browser control endpoint and produce the same state transition and invariant machine error code

## REMOVED Requirements

### Requirement: First-run readiness
**Reason**: The initial replacement release intentionally limits the built-in interface to the catalog-to-Acquisition path and does not include the previous readiness checklist.

**Migration**: Operators continue to use health checks and documented environment configuration; unchanged `/api/control/v1/integrations` diagnostics remain available to external clients and a later built-in UI increment.

### Requirement: Read-only integration diagnostics
**Reason**: Settings and diagnostic views are outside the approved initial replacement workflow and maintaining their Jinja implementation would create the rejected parallel legacy path.

**Migration**: Use the unchanged safe `/api/control/v1/integrations` resource or the existing operational health endpoints until a later UI change restores a built-in diagnostics view.
