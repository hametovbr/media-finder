# Bilingual Web UI Specification

## Purpose

Define an accessible bilingual, server-rendered interface for catalog management and deliberate release selection without introducing a separate client application.

## Requirements

### Requirement: Responsive catalog shell
The UI SHALL provide a desktop-first responsive shell with a collection sidebar, `Uncategorized`, Archive, Settings, About, and a poster-grid main view.

#### Scenario: Browse a collection
- **WHEN** a user selects a collection
- **THEN** the main view shows its active media cards in a responsive poster grid

#### Scenario: Poster artwork is absent or cannot load
- **WHEN** a catalog item has no normalized poster artwork or its external image fails
- **THEN** its card retains a stable poster-shaped local placeholder without requesting a remote fallback asset

### Requirement: Informative media cards
Each media card SHALL show title, year, media type, metadata provider, and the latest Acquisition state as `pending`, `submitted`, or `failed` when an attempt exists. A `pending` card SHALL indicate that manual reconciliation may be required and SHALL NOT imply client download progress. Cards SHALL NOT display download progress for any state.

#### Scenario: Acquisition remains pending
- **WHEN** an item's latest acquisition is pending manual reconciliation
- **THEN** the card shows `pending` with a manual-reconciliation indication and the item detail exposes the attempt without inventing download progress

### Requirement: Media detail navigation
A media-item page SHALL provide Overview, Seasons/Episodes for series, and Acquisitions views.

#### Scenario: Open a series
- **WHEN** a user opens a series card
- **THEN** the detail page exposes its overview, season/episode hierarchy including specials, and acquisition history

### Requirement: Explicit add workflow
Adding an item SHALL begin with metadata search or Manual entry, continue through confirmation and catalog save, and only then offer an optional `Find release` action. Results from different metadata providers SHALL be grouped separately and SHALL NOT be automatically merged.

#### Scenario: Add without downloading
- **WHEN** a user confirms metadata and declines `Find release`
- **THEN** the catalog item is saved without creating an Acquisition

#### Scenario: Select one provider result
- **WHEN** providers return similar results
- **THEN** the UI identifies each provider and requires one explicit selection

### Requirement: Explicit release submission UI
The release-search UI SHALL accept a free query and Prowlarr filters, then require explicit selection of a release and a live qBittorrent destination. The sole environment-owned qBittorrent instance SHALL be selected implicitly and SHALL NOT be configurable through the UI.

#### Scenario: Submit selected release
- **WHEN** a user selects a release and current destination and confirms
- **THEN** the UI initiates one idempotent Acquisition tied to the current metadata revision and the environment-owned qBittorrent identity

#### Scenario: qBittorrent is unavailable
- **WHEN** the environment-owned qBittorrent instance cannot be constructed or validated
- **THEN** the release UI reports a localized safe diagnostic and does not offer stale persisted clients

#### Scenario: Archive and restore a download-client instance
- **WHEN** a caller attempts to archive or restore a download-client instance through a former UI route
- **THEN** the request is rejected because the environment-owned qBittorrent identity has no user-managed lifecycle

### Requirement: First-run readiness
The UI SHALL show readiness for TMDB, Prowlarr, and the environment-owned qBittorrent instance without preventing Manual-only catalog use. Readiness SHALL distinguish a missing declared variable from a configured integration that is currently unavailable without revealing configured values.

#### Scenario: External integrations are absent
- **WHEN** required TMDB, Prowlarr, or qBittorrent environment variables are absent
- **THEN** the checklist reports the exact missing variable names and unavailable integrations while Manual item creation remains usable

#### Scenario: Configured upstream is unavailable
- **WHEN** every required variable is present but an upstream validation request fails
- **THEN** the checklist reports the integration as unavailable without displaying credentials, URLs containing secrets, or upstream response content

### Requirement: Read-only integration diagnostics
Settings SHALL provide a localized read-only view of installed integration declarations and their safe runtime status. It SHALL NOT provide mutating endpoints or controls for TMDB, Prowlarr, or download-client configuration or lifecycle.

#### Scenario: Inspect declared configuration
- **WHEN** a user opens Settings
- **THEN** the UI lists each exact declared variable name, whether it is required, whether it is secret, and a safe `set` or `missing` state without returning its value

#### Scenario: Attempt legacy configuration mutation
- **WHEN** a caller submits a former provider, Prowlarr, client-create, archive, or restore request
- **THEN** the application rejects the route without changing persisted or runtime integration state

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
