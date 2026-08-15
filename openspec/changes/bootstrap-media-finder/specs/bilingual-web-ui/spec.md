## Purpose

Define an accessible bilingual, server-rendered interface for catalog management and deliberate release selection without introducing a separate client application.

## ADDED Requirements

### Requirement: Responsive catalog shell
The UI SHALL provide a desktop-first responsive shell with a collection sidebar, `Uncategorized`, Archive, Settings, About, and a poster-grid main view.

#### Scenario: Browse a collection
- **WHEN** a user selects a collection
- **THEN** the main view shows its active media cards in a responsive poster grid

### Requirement: Informative media cards
Each media card SHALL show title, year, media type, metadata provider, and latest acquisition attempt as `submitted` or `failed`, and SHALL NOT display download progress.

#### Scenario: Acquisition remains pending
- **WHEN** an item's latest acquisition is pending manual reconciliation
- **THEN** the item detail exposes the pending attempt without inventing a download-progress state on the card

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
The release-search UI SHALL accept a free query and Prowlarr filters, then require explicit selection of a release, download-client instance, and live destination.

#### Scenario: Submit selected release
- **WHEN** a user selects a release, client, and current destination and confirms
- **THEN** the UI initiates one idempotent Acquisition tied to the current metadata revision

### Requirement: First-run readiness
The UI SHALL show readiness for TMDB, Prowlarr, and download clients without preventing Manual-only catalog use.

#### Scenario: External integrations are absent
- **WHEN** no TMDB, Prowlarr, or download client is configured
- **THEN** the checklist reports them unavailable while Manual item creation remains usable

### Requirement: Localized and accessible interaction
All user-facing UI text and stable API error codes SHALL be localizable in English and Russian. Critical flows SHALL support keyboard navigation, visible focus, associated labels, and semantic status feedback.

#### Scenario: Switch interface language
- **WHEN** a user selects Russian
- **THEN** subsequent UI pages use Russian localization while developer documentation and persisted provider identifiers remain unchanged

#### Scenario: Complete add flow by keyboard
- **WHEN** a keyboard-only user adds and confirms an item
- **THEN** every required control is reachable and the result is announced through semantic feedback

### Requirement: External-auth trust and CSRF protection
The UI SHALL maintain no user-account database and SHALL rely on external reverse-proxy authentication when exposed beyond localhost. Mutating UI requests SHALL require a valid signed session and CSRF token. Session cookies SHALL be `HttpOnly`, `SameSite=Lax`, and configurable as `Secure` for HTTPS.

#### Scenario: Missing CSRF token
- **WHEN** a browser submits a mutating UI request without a valid CSRF token
- **THEN** the system rejects the request without applying changes

#### Scenario: HTTPS deployment
- **WHEN** the operator enables secure-cookie mode behind an HTTPS reverse proxy
- **THEN** the session cookie includes the `Secure` attribute
