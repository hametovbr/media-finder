# Torrent Acquisition Specification

## Purpose

Define a deliberate torrent-selection and submission workflow that is idempotent, secret-safe, and independent of post-submission download tracking.

## Requirements

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

### Requirement: Live destination selection
The system SHALL use one environment-owned qBittorrent instance for new acquisitions and SHALL reload its categories immediately before submission. The user SHALL explicitly select a current destination but SHALL NOT select, create, edit, archive, or restore a download-client instance.

#### Scenario: Destination disappears
- **WHEN** a destination chosen from an older UI view no longer exists during the live reload
- **THEN** submission is rejected safely and the user receives the current destination list from the environment-owned qBittorrent instance

#### Scenario: qBittorrent environment is incomplete
- **WHEN** one or more required qBittorrent variables are absent
- **THEN** release submission is unavailable without affecting catalog or metadata operations

### Requirement: Idempotent acquisition creation
Before submitting, the system SHALL create a `pending` Acquisition with a UUID, idempotency key, pinned metadata revision, release-provider identity and version, download-client identity and version, destination, safe release snapshot, and naming-profile identifier. It SHALL NOT persist integration configuration, an environment reference, or a mutable client-instance record. Reusing the same idempotency key SHALL return the same Acquisition.

#### Scenario: Duplicate form submission
- **WHEN** the same idempotency key is submitted twice
- **THEN** both responses identify the same Acquisition and at most one client task is created

#### Scenario: Inspect historical module identity
- **WHEN** an Acquisition is read after the application has upgraded one of its statically packaged modules
- **THEN** its immutable snapshot still identifies the release-provider and download-client module versions used for the original submission

### Requirement: Safe release snapshot
An Acquisition SHALL persist only the release title, indexer, a validated safe GUID or canonical infohash when available, and an optional sanitized public source-page URL. A safe GUID SHALL be a 1–255 character ASCII opaque identifier restricted to letters, digits, `.`, `_`, `-`, and `:`, without whitespace, percent encoding, `://`, or path/query/fragment delimiters, and SHALL be explicitly classified as non-sensitive by the adapter. It SHALL NOT be a URL, path, credential, or unclassified token. A canonical infohash SHALL be lowercase hexadecimal with exactly 40 characters for BitTorrent v1 or 64 characters for BitTorrent v2. An uncertain or invalid GUID or infohash SHALL be omitted.

A source-page URL SHALL be accepted only from a dedicated public-page field with `http` or `https` scheme. Sanitization SHALL remove userinfo, query, fragment, path parameters, and every path segment not explicitly produced by an adapter's public-route normalizer. When safe path provenance cannot be established, the system SHALL store only the sanitized origin or omit the URL. The system SHALL omit any URL that is or may be a download URL or contain a passkey, credential, session identifier, or secret-bearing path token. Magnet URIs, torrent download URLs, torrent bytes, potential passkeys, rejected GUIDs, and rejected URL components SHALL NOT be persisted or logged.

#### Scenario: Source URL contains credentials and query
- **WHEN** a selected result has userinfo, query parameters, a fragment, and unclassified path segments in its source URL
- **THEN** the saved value contains at most a safe scheme, host, and port and none of the removed values appear in persistence or logs

#### Scenario: Passkey appears in a URL path
- **WHEN** a source or download URL contains a known or suspected passkey as a path segment
- **THEN** the system omits the secret-bearing path or entire URL and the passkey appears in neither persistence nor logs

#### Scenario: GUID is a secret-bearing URL
- **WHEN** an indexer supplies a URL, path, credential-like value, or unclassified token as its GUID
- **THEN** the system omits the GUID and does not log its rejected value

#### Scenario: Safe opaque GUID and infohash
- **WHEN** an adapter supplies an explicitly non-sensitive bounded opaque GUID and a valid canonical infohash
- **THEN** the snapshot may persist both normalized identifiers without persisting the release artifact or resolution URL

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

### Requirement: Bounded acquisition states
The MVP SHALL expose only `pending`, `submitted`, and `failed` acquisition states and SHALL NOT track progress after successful submission.

#### Scenario: Client rejects submission
- **WHEN** a client returns a definitive submission error
- **THEN** the Acquisition becomes `failed` with a safe error code

#### Scenario: Successful submission continues downloading
- **WHEN** a client task progresses or completes after submission
- **THEN** Media Finder leaves the Acquisition in `submitted` and does not mirror client progress

### Requirement: Ambiguous timeout recovery
On submission timeout, the system SHALL immediately query the selected client by exact correlation token before choosing `submitted` or `failed`. A `pending` Acquisition left by a crash SHALL change only through explicit manual reconciliation.

#### Scenario: Timeout after client acceptance
- **WHEN** submission times out but exact correlation lookup finds the task
- **THEN** the Acquisition becomes `submitted` without a duplicate submission

#### Scenario: Restart finds pending acquisition
- **WHEN** the service restarts with an Acquisition still `pending`
- **THEN** it does not automatically resubmit and offers manual reconciliation

#### Scenario: Retry a failed release
- **WHEN** a user retries after a failed Acquisition
- **THEN** the user performs a fresh search and the system creates a new Acquisition UUID
