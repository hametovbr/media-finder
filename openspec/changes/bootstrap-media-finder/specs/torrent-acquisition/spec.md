## Purpose

Define a deliberate torrent-selection and submission workflow that is idempotent, secret-safe, and independent of post-submission download tracking.

## ADDED Requirements

### Requirement: Manual torrent discovery
The system SHALL search Prowlarr only after a user supplies or confirms a free-form query and optional filters. It SHALL accept only BitTorrent results and SHALL present results for explicit user selection.

#### Scenario: Prowlarr returns mixed protocols
- **WHEN** a Prowlarr response contains torrent and Usenet results
- **THEN** the system presents only torrent results

### Requirement: Ephemeral release artifacts
Search results SHALL live only in an in-memory TTL cache, and the browser SHALL receive a safe opaque token. Magnet URIs, torrent bytes, download URLs, and passkey-bearing URL components SHALL NOT be persisted or logged.

#### Scenario: Search token expires
- **WHEN** a user submits an expired opaque result token
- **THEN** the system rejects it and requires a fresh search without revealing the underlying download URL

#### Scenario: Resolve a selected torrent
- **WHEN** a valid result token is selected
- **THEN** the Prowlarr adapter resolves a magnet URI or torrent bytes in memory and does not write the artifact to disk or the database

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
An Acquisition SHALL persist only the release title, indexer, GUID or infohash when available, and a sanitized source-page URL. Sanitization SHALL remove URL userinfo, query, and fragment. It SHALL NOT persist magnet URIs, torrent download URLs, torrent bytes, or potential passkeys.

#### Scenario: Source URL contains credentials and query
- **WHEN** a selected result has userinfo, query parameters, and a fragment in its source URL
- **THEN** the saved source URL contains only a safe scheme, host, port, and path

### Requirement: Exact client correlation
The system SHALL submit the exact correlation token `mf-acq-<acquisition-uuid>`. The qBittorrent module SHALL store the chosen destination as category and the exact correlation token as a tag.

#### Scenario: Submit to qBittorrent
- **WHEN** qBittorrent accepts a selected artifact
- **THEN** the torrent uses the selected category and an exact `mf-acq-<uuid>` tag, and the Acquisition becomes `submitted`

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
