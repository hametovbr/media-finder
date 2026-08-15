# Module Contracts and Retention Specification

## Purpose

Define stable, independently testable extension contracts while keeping configuration, secrets, and metadata retention ownership at the correct boundary.

## Requirements

### Requirement: Statically packaged modules
Metadata-provider and download-client modules SHALL be isolated Python packages shipped in the common application image. Runtime installation SHALL NOT be supported in the MVP.

#### Scenario: Add a third-party module
- **WHEN** a contributor adds a conforming module through a repository change
- **THEN** the production build includes it without requiring runtime package installation

#### Scenario: Compose registered first-party modules
- **WHEN** core constructs settings, retention, or a live module instance
- **THEN** it uses one static public registration boundary rather than provider- or client-specific switches

### Requirement: Module manifests and configuration
Every module SHALL provide a manifest, exact environment-variable declarations, translations, fixtures, capabilities, configuration validation, and conformance-test compatibility. Each environment declaration SHALL contain a non-empty exact variable name, required and secret classifications, and a localizable description key. Variable names SHALL be unique within a module and SHALL NOT be computed from persisted data or user input. Core SHALL NOT load module-supplied HTML or JavaScript and SHALL NOT render writable module configuration forms.

#### Scenario: Inspect module environment requirements
- **WHEN** core, documentation tooling, or an external contributor inspects a module manifest
- **THEN** it can determine every exact environment-variable name needed to construct that module without reading implementation internals

#### Scenario: Reject an invalid declaration
- **WHEN** a module declares a duplicate, empty, dynamically prefixed, or syntactically invalid environment-variable name
- **THEN** the shared conformance suite rejects the module

#### Scenario: Render module settings
- **WHEN** a module declares supported environment variables
- **THEN** core renders only generic localized read-only diagnostics and does not load module templates, scripts, or writable configuration controls

### Requirement: Metadata-provider contract
A metadata-provider module SHALL expose its exact environment-variable requirements, configuration validation, successful search, successful identity-based fetch, normalization, attribution, standardized errors, provider-owned retention hooks, and a typed export-warning hook without direct database or UI-template access. Every provider manifest SHALL advertise `search`, `fetch`, and `normalize` as essential capabilities. The export-warning hook SHALL return only deeply immutable, allowlisted, validated response-header values or no warning. Core SHALL defensively revalidate a returned warning before consuming it.

#### Scenario: Conform an external provider
- **WHEN** a test provider implements the public metadata contract using only its fixtures and public types
- **THEN** the shared conformance suite requires exact environment declarations and an expected safe error code and unconditionally validates successful search, fetch, normalization, locale, identity, that standardized error, attribution, retention, missing-variable behavior, and secret classification without knowledge of provider internals

#### Scenario: Conform the Manual provider
- **WHEN** the Manual provider is supplied an in-memory conformance fixture identity
- **THEN** it declares no required environment variables and searches and fetches that fixture through the same public protocol without database or UI access

#### Scenario: Supply an export warning
- **WHEN** a provider has a retention deadline that external processors need to know
- **THEN** its export-warning hook returns validated safe headers through the public provider contract without a provider-specific core branch

### Requirement: Download-client contract
A download-client module SHALL expose its exact environment-variable requirements, validate resolved environment configuration, list live destinations, submit either a magnet URI or in-memory torrent bytes, find a task by correlation token, and guarantee exact preservation of that token without direct database or UI-template access.

#### Scenario: Conform an external client
- **WHEN** a test client implements the public download-client contract using only its fixtures and public types
- **THEN** the shared capability-aware conformance suite validates exact environment declarations, missing-variable behavior, destination listing, only its declared artifact forms, correlation preservation, standardized errors, and lookup

### Requirement: Provider-owned retention
Each metadata provider SHALL determine whether and when its derived payload needs refresh or expiry. Core SHALL only invoke generic due hooks at application startup and once per day and persist their outcomes; core SHALL NOT encode a provider name or provider-specific duration. Core SHALL invoke every installed and registered provider type that owns persisted revisions, even when no active provider instance is currently configured.

#### Scenario: TMDB retention dates
- **WHEN** the TMDB module creates a provider-derived revision
- **THEN** it sets `refresh_after` to five calendar months and `expires_at` to six calendar months according to its own policy

#### Scenario: TMDB revision reaches expiry
- **WHEN** a TMDB-derived revision reaches its module-computed `expires_at`
- **THEN** the TMDB retention hook returns a mandatory purge action for its raw, normalized, and effective provider-derived payload

#### Scenario: Refreshed revision later reaches expiry
- **WHEN** a revision has refreshed successfully and later reaches its original provider-computed expiry
- **THEN** core does not refresh it repeatedly and still applies the provider's mandatory purge action

#### Scenario: One retention subject fails unexpectedly
- **WHEN** a provider or normalized-payload validation unexpectedly fails for one revision
- **THEN** core rolls back only that revision's savepoint, records a standardized safe failure in an isolated savepoint, and continues maintenance for later revisions, including mandatory purges, without erasing earlier outcomes

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
All TMDB, Prowlarr, and download-client configuration, including non-secret service addresses and credentials, SHALL enter only through exact environment variables declared by their owning module or integration descriptor. Core SHALL NOT persist integration configuration or environment references in application settings or client configuration payloads. Resolved values SHALL NOT appear in UI/API output, exceptions, structured logs, diagnostics, or module manifests.

#### Scenario: Construct an integration
- **WHEN** core constructs TMDB, Prowlarr, or qBittorrent
- **THEN** it resolves the exact declared variables from the current process environment and does not read an integration setting from the database

#### Scenario: Save client credentials
- **WHEN** an operator supplies qBittorrent credentials through the declared environment variables
- **THEN** the database stores neither the resolved credentials nor environment-variable references and the UI provides no credential-save operation

#### Scenario: Required variable is absent
- **WHEN** a required declared environment variable is absent or empty
- **THEN** the integration is unavailable with a stable safe error that identifies only the missing variable name and never a secret value

#### Scenario: External service failure includes a secret
- **WHEN** an upstream exception contains a credential or sensitive URL component
- **THEN** the system emits a redacted error and safe diagnostic details
