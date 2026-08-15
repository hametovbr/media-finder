## Purpose

Define a deliberate torrent-selection and submission workflow that is idempotent, secret-safe, and independent of post-submission download tracking.

## ADDED Requirements

### Requirement: Manual torrent discovery
The system SHALL search Prowlarr only after a user supplies or confirms a free-form query and optional filters. It SHALL accept only BitTorrent results and SHALL present results for explicit user selection.

#### Scenario: Prowlarr returns mixed protocols
- **WHEN** a Prowlarr response contains torrent and Usenet results
- **THEN** the system presents only torrent results

### Requirement: Ephemeral release artifacts
Search results SHALL live only in a bounded in-memory TTL cache, and the browser SHALL receive a safe opaque token. Prowlarr JSON payloads, returned result counts, UI form bodies, and resolved torrent bytes SHALL have enforced bounds with stable safe errors. Magnet URIs, torrent bytes, complete download URLs, and passkey-bearing URL components SHALL NOT be persisted or logged, including by underlying HTTP client loggers.

#### Scenario: Search token expires
- **WHEN** a user submits an expired opaque result token
- **THEN** the system rejects it and requires a fresh search without revealing the underlying download URL

#### Scenario: Resolve a selected torrent
- **WHEN** a valid result token is selected
- **THEN** the Prowlarr adapter resolves a magnet URI or torrent bytes in memory and does not write the artifact to disk or the database

#### Scenario: Constrain authenticated torrent resolution
- **WHEN** Prowlarr is configured behind a reverse-proxy path and a selected download URL escapes that normalized path through an unrelated prefix, prefix confusion, or encoded traversal
- **THEN** the adapter rejects the URL before resolving or sending the API key, while a URL within the configured path remains eligible for in-memory resolution

#### Scenario: Reject oversized integration input
- **WHEN** a UI form, Prowlarr response, result set, or torrent artifact exceeds its declared bound
- **THEN** the system rejects it with a stable safe code without persisting or logging sensitive content and a selected release token remains one-use

### Requirement: Live destination selection
The system SHALL support named download-client instances and SHALL reload destinations from the selected client immediately before submission. The user SHALL explicitly select a current destination.

#### Scenario: Destination disappears
- **WHEN** a destination chosen from an older UI view no longer exists during the live reload
- **THEN** submission is rejected safely and the user receives the current destination list

### Requirement: Idempotent acquisition creation
Before submitting, the system SHALL create a `pending` Acquisition with a UUID, idempotency key, pinned metadata revision, selected download-client instance, destination, release snapshot, and naming-profile identifier. Reusing the same idempotency key SHALL return the same Acquisition.

#### Scenario: Duplicate form submission
- **WHEN** the same idempotency key is submitted twice
- **THEN** both responses identify the same Acquisition and at most one client task is created

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
The system SHALL submit the exact correlation token `mf-acq-<acquisition-uuid>`. The qBittorrent module SHALL store the chosen destination as category and the exact correlation token as a tag. Authenticated HTTP sessions SHALL be isolated between TMDB, Prowlarr, and every qBittorrent instance so a cookie from one service or port cannot reach another.

#### Scenario: Submit to qBittorrent
- **WHEN** qBittorrent accepts a selected artifact
- **THEN** the torrent uses the selected category and an exact `mf-acq-<uuid>` tag, and the Acquisition becomes `submitted`

#### Scenario: Live integration construction fails
- **WHEN** Prowlarr validation or a metadata-provider or download-client builder fails after creating one or more HTTP clients
- **THEN** the runtime validates before caching, immediately closes and forgets every client created by that failed attempt, including across repeated failures, and leaves unrelated successful cached integrations open

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

#### Scenario: Reconcile after Prowlarr becomes unavailable
- **WHEN** a pinned `pending` Acquisition is manually reconciled after Prowlarr has been removed or become unavailable
- **THEN** the system queries only the pinned active download-client instance by the exact correlation token and does not require Prowlarr

#### Scenario: Retry a failed release
- **WHEN** a user retries after a failed Acquisition
- **THEN** the user performs a fresh search and the system creates a new Acquisition UUID
