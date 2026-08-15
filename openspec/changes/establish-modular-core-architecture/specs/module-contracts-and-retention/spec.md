## MODIFIED Requirements

### Requirement: Statically packaged modules
Metadata-provider, release-provider, and download-client modules SHALL be isolated, separately buildable packages shipped in the common application image. Runtime installation SHALL NOT be supported in the MVP.

#### Scenario: Add a third-party module
- **WHEN** a contributor adds a conforming module through a repository change and explicit host registration
- **THEN** the production build includes it without requiring runtime package installation or a core-internal import

#### Scenario: Compose registered first-party modules
- **WHEN** the host constructs metadata, release discovery, retention, or download-client behavior
- **THEN** it uses one static public registration boundary rather than provider-, release-source-, or client-specific switches in core

### Requirement: Module manifests and configuration
Every module SHALL provide a machine-readable manifest, exact environment-variable declarations, translations, fixtures, capabilities, configuration validation, and conformance-test compatibility. The manifest SHALL declare a stable module identifier, specialized module kind, module version, supported SDK range, operation-contract version, capabilities, attribution when applicable, and translation keys. Each environment declaration SHALL contain a non-empty exact variable name, required and secret classifications, and a localizable description key. Variable names SHALL be unique within a module and SHALL NOT be computed from persisted data or user input. Core SHALL NOT load module-supplied HTML or JavaScript and SHALL NOT render writable module configuration forms.

#### Scenario: Inspect module environment requirements
- **WHEN** core, build tooling, documentation tooling, or a contributor inspects a module manifest
- **THEN** it can determine identity, compatibility, kind, capabilities, attribution, translations, and every exact environment-variable name without importing module implementation internals

#### Scenario: Reject an incompatible manifest
- **WHEN** a module declares an invalid identity, unsupported SDK range, unsupported contract version, kind-registration mismatch, or capability inconsistent with its contract
- **THEN** registry or conformance validation rejects the module before application startup

#### Scenario: Reject an invalid declaration
- **WHEN** a module declares a duplicate, empty, dynamically prefixed, or syntactically invalid environment-variable name
- **THEN** the shared conformance suite rejects the module

#### Scenario: Render module settings
- **WHEN** a module declares supported environment variables
- **THEN** core renders only generic localized read-only diagnostics and does not load module templates, scripts, or writable configuration controls

### Requirement: Environment-only secrets
All TMDB, Prowlarr, and download-client configuration, including non-secret service addresses and credentials, SHALL enter only through exact environment variables declared by their owning module manifest. Core SHALL resolve only those declarations and pass an immutable value set to the selected module factory; a module SHALL NOT receive a process-wide secret resolver or require persisted configuration. Core SHALL NOT persist integration configuration or environment references in application settings or client configuration payloads. Resolved values SHALL NOT appear in UI/API output, exceptions, structured logs, diagnostics, schemas, fixtures, or module manifests.

#### Scenario: Construct an integration
- **WHEN** the host constructs TMDB, Prowlarr, or qBittorrent
- **THEN** core resolves exactly the owning manifest's declared variables from the current process environment and does not read an integration setting from the database

#### Scenario: Module requests an undeclared variable
- **WHEN** a module implementation attempts to obtain a process variable not present in its manifest declarations
- **THEN** the supported module construction contract supplies no such value and conformance rejects any fixture or configuration dependency on it

#### Scenario: Save client credentials
- **WHEN** an operator supplies download-client credentials through declared environment variables
- **THEN** the database stores neither the resolved credentials nor environment-variable references and the UI provides no credential-save operation

#### Scenario: Required variable is absent
- **WHEN** a required declared environment variable is absent or empty
- **THEN** the integration is unavailable with a stable safe error that identifies only the missing variable name and never a secret value

#### Scenario: External service failure includes a secret
- **WHEN** an upstream exception contains a credential or sensitive URL component
- **THEN** the system emits a redacted error and safe diagnostic details

## ADDED Requirements

### Requirement: Release-provider contract
A release-provider module SHALL expose exact environment requirements, resolved-configuration validation, bounded torrent-only search, safe release snapshots, resolution of a core-held opaque selection into an in-memory magnet or torrent artifact, and standardized errors without direct access to persistence, acquisition services, browser tokens, or UI templates.

#### Scenario: Conform an external release provider
- **WHEN** a test release provider implements the public release contract using only its manifest, public types, and fixtures
- **THEN** the capability-specific conformance suite validates environment declarations, bounded search, torrent-only results, safe snapshot fields, artifact resolution, standardized errors, secret redaction, and declared artifact capabilities without knowledge of provider internals

#### Scenario: Conform Prowlarr
- **WHEN** the first-party Prowlarr package is built
- **THEN** it passes the same release-provider conformance suite and registration validation required of any repository-contributed release provider

### Requirement: Public module SDK artifacts
The module SDK SHALL publish only capability DTOs, specialized protocols, manifest schemas, registration contracts, stable error categories, and conformance fixtures required by module authors. Specialized protocols SHALL include metadata retrieval, optional metadata editing within a metadata-provider registration, release discovery, and download-client behavior. It SHALL NOT expose core persistence, repositories, application services, framework routers, or a general dependency-injection container. Deterministic JSON Schemas and fixtures SHALL accompany the Python binding.

#### Scenario: Build a module against the SDK
- **WHEN** a contributor builds a metadata, release, or download module in isolation
- **THEN** the module imports only the public SDK and implementation libraries and can run its conformance suite without installing core

#### Scenario: Detect contract drift
- **WHEN** a public SDK DTO, manifest field, error category, or fixture changes without the corresponding versioned schema artifact and OpenSpec change
- **THEN** required CI verification fails

### Requirement: Capability-specific registration
The static registry SHALL maintain separate typed registrations for metadata providers, release providers, and download clients. A metadata-provider registration MAY expose a typed metadata-editor factory only when its manifest declares the matching capability. Each registration SHALL match its manifest kind and SHALL expose only the factory and lifecycle operations needed for that capability. There SHALL NOT be a universal callback, priority-ordered hook chain, module-to-module lookup facility, or shared mutable context object.

#### Scenario: Register mismatched capability
- **WHEN** a metadata provider is registered as a release provider or a declared capability lacks the required specialized operation
- **THEN** registry validation fails before the application begins serving requests

#### Scenario: First-party and contributor parity
- **WHEN** the host registers a first-party module
- **THEN** it follows the same typed registration and conformance path as a repository-contributed module and receives no privileged core access

### Requirement: Metadata editing sub-capability
A metadata-provider module MAY expose a `MetadataEditor` sub-capability for provider-owned structured import and edit semantics. The editor SHALL accept only bounded SDK input values, SHALL return validated normalized metadata and identity values, and SHALL NOT receive persistence, control DTOs, HTTP requests, templates, or a general extension context. Core SHALL own confirmation, atomic persistence, immutable revision creation, and orchestration without branching on a concrete metadata-provider identifier.

#### Scenario: Conform a metadata editor
- **WHEN** a metadata module declares the `metadata-edit` capability
- **THEN** its registration supplies a typed editor factory and conformance validates structured import, invalid identity, bounded episode-table merge, standardized errors, and lifecycle cleanup without installing core

#### Scenario: Preserve Manual editing without core coupling
- **WHEN** a user creates or edits Manual metadata or imports episode CSV
- **THEN** core invokes the injected metadata editor, validates its SDK output, and persists the operation atomically without importing the Manual package or parsing the Manual dialect itself

#### Scenario: Reject an editor mismatch
- **WHEN** a manifest declares `metadata-edit` without a typed editor factory, or a registration supplies an editor without that capability
- **THEN** registry validation fails before application startup
