## MODIFIED Requirements

### Requirement: Manual torrent discovery
The system SHALL delegate release discovery to the statically selected registered release-provider module only after a user supplies or confirms a free-form query and optional filters. It SHALL accept only BitTorrent results and SHALL present results for explicit user selection. The default first-party composition SHALL use Prowlarr through that release-provider contract.

#### Scenario: Prowlarr returns mixed protocols
- **WHEN** the first-party Prowlarr release-provider response contains torrent and non-torrent results
- **THEN** the system presents only torrent results

#### Scenario: Replace the first-party release provider
- **WHEN** a conforming release provider replaces Prowlarr through an explicit repository and host-composition change
- **THEN** acquisition uses the same core search, opaque-selection, snapshot, and submission workflow without provider-specific core branches

### Requirement: Ephemeral release artifacts
Search results SHALL live only in a core-owned bounded in-memory TTL cache, and the browser SHALL receive a safe opaque token. Release-provider payloads, returned result counts, UI form bodies, and resolved torrent bytes SHALL have enforced bounds with stable safe errors. Magnet URIs, torrent bytes, complete download URLs, and passkey-bearing URL components SHALL NOT be persisted or logged, including by underlying HTTP client loggers.

#### Scenario: Search token expires
- **WHEN** a user submits an expired opaque result token
- **THEN** the system rejects it and requires a fresh search without revealing the underlying resolution data

#### Scenario: Resolve a selected torrent
- **WHEN** a valid result token is selected
- **THEN** core consumes it once and asks the owning release-provider module to resolve a magnet URI or torrent bytes in memory without writing the artifact to disk or the database

#### Scenario: Reject oversized integration input
- **WHEN** a UI form, release-provider response, result set, or torrent artifact exceeds its declared bound
- **THEN** the system rejects it with a stable safe code without persisting or logging sensitive content and the selected release token remains one-use

### Requirement: Idempotent acquisition creation
Before submitting, the system SHALL create a `pending` Acquisition with a UUID, idempotency key, pinned metadata revision, release-provider identity and version, download-client identity and version, destination, safe release snapshot, and naming-profile identifier. It SHALL NOT persist integration configuration, an environment reference, or a mutable client-instance record. Reusing the same idempotency key SHALL return the same Acquisition.

#### Scenario: Duplicate form submission
- **WHEN** the same idempotency key is submitted twice
- **THEN** both responses identify the same Acquisition and at most one client task is created

#### Scenario: Inspect historical module identity
- **WHEN** an Acquisition is read after the application has upgraded one of its statically packaged modules
- **THEN** its immutable snapshot still identifies the release-provider and download-client module versions used for the original submission

### Requirement: Exact client correlation
The system SHALL submit the exact correlation token `mf-acq-<acquisition-uuid>`. The environment-owned qBittorrent module SHALL store the chosen destination as category and the exact correlation token as a tag. Authenticated HTTP sessions SHALL be isolated between metadata providers, release providers, and download clients so cookies or authorization state from one integration or port cannot reach another.

#### Scenario: Submit to qBittorrent
- **WHEN** qBittorrent accepts a selected artifact
- **THEN** the torrent uses the selected category and an exact `mf-acq-<uuid>` tag, and the Acquisition becomes `submitted`

#### Scenario: Live integration construction fails
- **WHEN** a release-provider, metadata-provider, or download-client construction or live validation attempt fails after allocating one or more resources
- **THEN** the module lifecycle immediately closes and forgets every resource owned by that failed attempt and leaves unrelated successful cached modules open

#### Scenario: Reconcile after a compatible download-client upgrade
- **WHEN** a pending Acquisition is reconciled after the statically selected download-client module has been upgraded while retaining the same stable module ID
- **THEN** the currently packaged module performs the exact-correlation lookup, the Acquisition retains its original immutable module-version snapshot, and no release provider is required

#### Scenario: Reconcile after download-client replacement or removal
- **WHEN** a pending Acquisition identifies a download-client module ID that is missing or differs from the statically selected download-client module
- **THEN** reconciliation returns a stable safe unavailable-or-mismatch result, performs no lookup through the foreign client, and leaves the Acquisition pending for a future compatible reconcile

## REMOVED Requirements

### Requirement: Preserve historical client references
**Reason**: Environment-only configuration and the new immutable Acquisition module snapshot replace mutable persisted download-client instances. There is no supported user-data upgrade obligation at this pre-release stage, so retaining the legacy table would preserve an unnecessary internal compatibility surface.

**Migration**: Replace the existing development database with the new initial schema. New Acquisitions persist download-client module identity and version directly; no credentials, environment references, or mutable client-instance configuration are migrated.
