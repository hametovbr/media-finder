## Purpose

Define stable, independently testable extension contracts while keeping configuration, secrets, and metadata retention ownership at the correct boundary.

## ADDED Requirements

### Requirement: Statically packaged modules
Metadata-provider and download-client modules SHALL be isolated Python packages shipped in the common application image. Runtime installation SHALL NOT be supported in the MVP.

#### Scenario: Add a third-party module
- **WHEN** a contributor adds a conforming module through a repository change
- **THEN** the production build includes it without requiring runtime package installation

### Requirement: Module manifests and configuration
Every module SHALL provide a manifest, typed configuration schema, translations, fixtures, capabilities, configuration validation, and conformance-test compatibility. Core SHALL render settings from the schema and SHALL reject module-supplied HTML or JavaScript.

#### Scenario: Render module settings
- **WHEN** a module declares supported typed settings
- **THEN** core renders generic localized controls without loading module templates or scripts

### Requirement: Metadata-provider contract
A metadata-provider module SHALL expose configuration validation, search, fetch, normalization, attribution, standardized errors, and provider-owned retention hooks without direct database or UI-template access.

#### Scenario: Conform an external provider
- **WHEN** a test provider implements the public metadata contract using only its fixtures and public types
- **THEN** the shared conformance suite validates it without knowledge of the provider internals

### Requirement: Download-client contract
A download-client module SHALL validate configuration, list live destinations, submit either a magnet URI or in-memory torrent bytes, find a task by correlation token, and guarantee exact preservation of that token without direct database or UI-template access.

#### Scenario: Conform an external client
- **WHEN** a test client implements the public download-client contract using only its fixtures and public types
- **THEN** the shared conformance suite validates destination listing, both artifact forms, correlation preservation, and lookup

### Requirement: Provider-owned retention
Each metadata provider SHALL determine whether and when its derived payload needs refresh or expiry. Core SHALL only invoke generic due hooks at application startup and once per day and persist their outcomes; core SHALL NOT encode a provider name or provider-specific duration. Core SHALL invoke every installed and registered provider type that owns persisted revisions, even when no active provider instance is currently configured.

#### Scenario: TMDB retention dates
- **WHEN** the TMDB module creates a provider-derived revision
- **THEN** it sets `refresh_after` to five calendar months and `expires_at` to six calendar months according to its own policy

#### Scenario: TMDB revision reaches expiry
- **WHEN** a TMDB-derived revision reaches its module-computed `expires_at`
- **THEN** the TMDB retention hook returns a mandatory purge action for its raw, normalized, and effective provider-derived payload

#### Scenario: Purge an expired provider payload
- **WHEN** a provider retention hook returns a purge action
- **THEN** core removes the specified provider-derived payload while retaining the revision envelope, identity, overrides, and acquisition history

#### Scenario: Run generic maintenance
- **WHEN** the service starts or the daily maintenance interval elapses
- **THEN** core asks every installed registered provider owning persisted revisions for due work without applying provider-specific dates itself

#### Scenario: Provider configuration was removed
- **WHEN** persisted revisions remain for a provider whose active configuration was removed
- **THEN** core still invokes that provider's retention hook and applies due purge actions

### Requirement: Environment-only secrets
Secrets SHALL enter through environment variables. Persisted module and application settings SHALL contain only references in the form `env:VARIABLE_NAME`, and secrets SHALL NOT appear in UI/API output, exceptions, structured logs, or diagnostics.

#### Scenario: Save client credentials
- **WHEN** a user configures a download-client secret reference
- **THEN** the database stores the environment-variable reference and never the resolved value

#### Scenario: External service failure includes a secret
- **WHEN** an upstream exception contains a credential or sensitive URL component
- **THEN** the system emits a redacted error and safe diagnostic details
