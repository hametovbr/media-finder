## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Read-only integration diagnostics
Settings SHALL provide a localized read-only view of installed integration declarations and their safe runtime status. It SHALL NOT provide mutating endpoints or controls for TMDB, Prowlarr, or download-client configuration or lifecycle.

#### Scenario: Inspect declared configuration
- **WHEN** a user opens Settings
- **THEN** the UI lists each exact declared variable name, whether it is required, whether it is secret, and a safe `set` or `missing` state without returning its value

#### Scenario: Attempt legacy configuration mutation
- **WHEN** a caller submits a former provider, Prowlarr, client-create, archive, or restore request
- **THEN** the application rejects the route without changing persisted or runtime integration state
