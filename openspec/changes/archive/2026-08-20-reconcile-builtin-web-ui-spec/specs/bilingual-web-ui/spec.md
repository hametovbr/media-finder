## MODIFIED Requirements

### Requirement: Supported built-in workflow
The built-in interface SHALL expose catalog browsing, read-only collection filtering, media overview, metadata-provider search and explicit selection, release search and explicit selection, live destination selection, and idempotent Acquisition submission. It SHALL NOT expose Manual create, edit, import, or episode CSV controls; collection or media-item mutation controls; Acquisition history or reconciliation controls; integration diagnostics; Settings; or About. The omitted workflows SHALL remain available through their unchanged browser control API operations for future interfaces and later increments.

#### Scenario: Complete the supported path
- **WHEN** a user browses the catalog, selects provider metadata, chooses a release and current destination, and confirms submission
- **THEN** the interface completes the path through `/api/control/v1` and presents the resulting Acquisition state without requiring an omitted secondary workflow

#### Scenario: Open an omitted secondary route
- **WHEN** a user navigates to a removed route for Manual editing, Settings, diagnostics, About, or Acquisition reconciliation
- **THEN** the client presents localized not-found feedback and does not invoke a legacy HTML handler or mutate state

### Requirement: Informative media cards
Each media card SHALL show title, year, media type, metadata provider, and the latest Acquisition state as `pending`, `submitted`, or `failed` when an attempt exists. A `pending` card SHALL indicate that manual reconciliation may be required and SHALL NOT imply client download progress. Cards SHALL NOT display download progress for any state.

#### Scenario: Acquisition remains pending
- **WHEN** an item's latest acquisition is pending manual reconciliation
- **THEN** the card shows `pending` with a manual-reconciliation indication without inventing download progress or exposing a reconciliation control in the supported built-in interface

### Requirement: Media detail navigation
A media-item page SHALL provide the normalized overview and a `Find release` action. The built-in interface SHALL NOT expose season and episode hierarchy or Acquisition-history views.

#### Scenario: Open a series
- **WHEN** a user opens a series card
- **THEN** the detail page exposes its normalized overview and release-search action without claiming that omitted season, episode, or Acquisition-history views are available

### Requirement: Explicit add workflow
Adding an item SHALL begin with metadata-provider search, continue through explicit provider-scoped result selection and any required similarity confirmation, save the catalog item, and only then offer an optional `Find release` action. Results from different metadata providers SHALL be grouped separately and SHALL NOT be automatically merged. The built-in interface SHALL NOT expose Manual entry or import.

#### Scenario: Add without downloading
- **WHEN** a user confirms provider metadata and declines `Find release`
- **THEN** the catalog item is saved without creating an Acquisition

#### Scenario: Select one provider result
- **WHEN** providers return similar results
- **THEN** the UI identifies each provider and requires one explicit selection

#### Scenario: Metadata selection expires
- **WHEN** a metadata selection token is expired, consumed, evicted, or invalidated by restart
- **THEN** the interface displays localized safe feedback and returns the user to metadata search without replaying the stale selection

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

### Requirement: Independently buildable built-in interface
The bundled interface SHALL be delivered as a separately buildable package whose browser source consumes the deterministic public control OpenAPI contract and presentation libraries only. It SHALL NOT require database, persistence-model, domain-service, runtime-integration, metadata-provider, download-client, backend repository, or processor SDK imports. Its deterministic development mode SHALL render the supported built-in workflow, English and Russian states, responsive layouts, and safe errors with typed fake HTTP responses and no database or external integration.

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
The built-in interface SHALL preserve GET navigation for `/`, `/add`, `/items/{item_id}`, and `/items/{item_id}/releases` as client routes with equivalent supported outcomes. Removed server-rendered form actions, fragment endpoints, and secondary HTML routes SHALL NOT remain as a parallel presentation path. Their removal SHALL NOT alter the backend control, processor, persistence, or integration semantics.

#### Scenario: Use an existing bookmark and form workflow
- **WHEN** a user upgrades across the built-in UI replacement boundary, opens a supported bookmark, or submits a formerly supported server-rendered form
- **THEN** the GET bookmark renders the corresponding client route, while the removed form submission is rejected without changing state and the supported operation remains available through `/api/control/v1`

#### Scenario: Use a supported bookmark
- **WHEN** a user opens a catalog, add, item-detail, or release-selection bookmark
- **THEN** the built-in client renders the corresponding supported route and obtains its state from the browser control API

#### Scenario: Submit a legacy form action
- **WHEN** a caller submits a removed Jinja or HTMX form or fragment route
- **THEN** the application rejects the unsupported route without invoking a second domain path or changing state

#### Scenario: Compare built-in and control behavior
- **WHEN** a supported built-in workflow and a direct browser control request perform the same catalog, metadata, release, or Acquisition operation
- **THEN** both use the same browser control endpoint and produce the same state transition and invariant machine error code

## RENAMED Requirements

- FROM: `### Requirement: Initial replacement workflow`
- TO: `### Requirement: Supported built-in workflow`
