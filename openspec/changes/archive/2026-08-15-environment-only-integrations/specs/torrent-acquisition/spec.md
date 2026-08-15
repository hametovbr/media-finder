## MODIFIED Requirements

### Requirement: Live destination selection
The system SHALL use one environment-owned qBittorrent instance for new acquisitions and SHALL reload its categories immediately before submission. The user SHALL explicitly select a current destination but SHALL NOT select, create, edit, archive, or restore a download-client instance.

#### Scenario: Destination disappears
- **WHEN** a destination chosen from an older UI view no longer exists during the live reload
- **THEN** submission is rejected safely and the user receives the current destination list from the environment-owned qBittorrent instance

#### Scenario: qBittorrent environment is incomplete
- **WHEN** one or more required qBittorrent variables are absent
- **THEN** release submission is unavailable without affecting catalog or metadata operations

### Requirement: Idempotent acquisition creation
Before submitting, the system SHALL create a `pending` Acquisition with a UUID, idempotency key, pinned metadata revision, the stable environment-owned qBittorrent client record, destination, release snapshot, and naming-profile identifier. Reusing the same idempotency key SHALL return the same Acquisition.

#### Scenario: Duplicate form submission
- **WHEN** the same idempotency key is submitted twice
- **THEN** both responses identify the same Acquisition and at most one client task is created

### Requirement: Exact client correlation
The system SHALL submit the exact correlation token `mf-acq-<acquisition-uuid>`. The environment-owned qBittorrent module SHALL store the chosen destination as category and the exact correlation token as a tag. Authenticated HTTP sessions SHALL be isolated between TMDB, Prowlarr, and qBittorrent so a cookie from one service or port cannot reach another.

#### Scenario: Submit to qBittorrent
- **WHEN** qBittorrent accepts a selected artifact
- **THEN** the torrent uses the selected category and an exact `mf-acq-<uuid>` tag, and the Acquisition becomes `submitted`

#### Scenario: Live integration construction fails
- **WHEN** Prowlarr validation or a metadata-provider or qBittorrent builder fails after creating one or more HTTP clients
- **THEN** the runtime validates before caching, immediately closes and forgets every client created by that failed attempt, including across repeated failures, and leaves unrelated successful cached integrations open

## ADDED Requirements

### Requirement: Preserve historical client references
The system SHALL retain download-client rows referenced by existing Acquisitions while preventing legacy persisted configurations from being used for new discovery, submission, or reconciliation. It SHALL maintain one stable system-owned qBittorrent client identity for new Acquisitions.

#### Scenario: Upgrade a database with client history
- **WHEN** an existing deployment containing named client instances is upgraded
- **THEN** historical Acquisition records remain readable and new Acquisitions reference only the system-owned qBittorrent identity
