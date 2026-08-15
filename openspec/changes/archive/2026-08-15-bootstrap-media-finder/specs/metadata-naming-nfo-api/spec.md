## Purpose

Provide external processors with stable, secure metadata and export contracts without coupling Media Finder to any media-container format or filesystem workflow.

## ADDED Requirements

### Requirement: Integration authentication and errors
Every `/api/v1/*` endpoint SHALL require one Bearer integration token sourced from the environment. API errors SHALL contain a stable machine code, request ID, and safe details. Health endpoints SHALL remain unauthenticated.

#### Scenario: Missing integration token
- **WHEN** a caller requests an `/api/v1/*` resource without the configured Bearer token
- **THEN** the system returns an authentication error envelope and does not expose secret values

#### Scenario: Request fails validation
- **WHEN** an authenticated request contains invalid parameters
- **THEN** the response includes a stable error code and request ID suitable for safe support diagnostics

#### Scenario: Framework routing fails
- **WHEN** routing produces a not-found or method-not-allowed response
- **THEN** the response uses the same stable request-ID error envelope and does not expose the framework's default detail body

### Requirement: Pinned and current metadata APIs
The system SHALL expose the pinned effective normalized snapshot at `GET /api/v1/acquisitions/{id}/metadata` and the current effective normalized snapshot at `GET /api/v1/media-items/{id}/metadata`. Responses SHALL include schema version, provenance, locale, completeness, and structural quality and SHALL NOT expose raw provider payloads.

#### Scenario: Read pinned acquisition metadata
- **WHEN** an acquisition pins an older non-expired revision and the media item has a newer revision
- **THEN** the acquisition endpoint returns the older effective normalized snapshot

### Requirement: Expired provider-derived exports
At or after a module-computed provider expiry, metadata, naming, and NFO exports that depend on that provider-derived payload SHALL return HTTP 410 with code `metadata_source_expired`, whether or not scheduled physical purge has completed. TMDB-derived NFO responses that remain available before expiry SHALL carry module-supplied expiry warning headers.

#### Scenario: Request purged pinned metadata
- **WHEN** a caller requests an acquisition whose pinned provider-derived payload has expired
- **THEN** the API returns 410 `metadata_source_expired` while retaining the acquisition and revision identity

#### Scenario: Maintenance has not purged expired bytes yet
- **WHEN** a provider-derived revision has reached `expires_at` but its daily purge has not completed
- **THEN** export endpoints return 410 and do not serve the expired provider-derived payload

#### Scenario: Export non-expired TMDB NFO
- **WHEN** a caller exports NFO from a non-expired TMDB revision
- **THEN** the response includes module-supplied expiry warning headers and does not create a provenance sidecar

### Requirement: Versioned naming endpoints
The system SHALL expose current naming at `GET /api/v1/media-items/{id}/exports/naming` and pinned naming at `GET /api/v1/acquisitions/{id}/exports/naming`. Query parameters SHALL identify `entity_type` as `movie`, `tvshow`, `season`, or `episode`; provide season and episode numbers when required; select `profile=jellyfin-v1`; and optionally provide `target_extension`. A successful JSON response SHALL contain `profile`, `relative_directory`, `basename`, nullable `target_extension`, `relative_path`, and `nfo_filename`.

#### Scenario: Request pinned episode naming
- **WHEN** an authenticated caller requests Acquisition naming with `entity_type=episode`, a valid season number, and one or more episode numbers
- **THEN** the response is derived from the pinned effective revision and contains every defined naming response field

#### Scenario: Naming selector is incomplete
- **WHEN** an episode naming request omits its season or episode selector
- **THEN** the API returns a stable validation error envelope and creates no state

### Requirement: Extension-independent Jellyfin naming
The fixed `jellyfin-v1` profile SHALL return the versioned naming-endpoint response for a movie, series episode, Season 00 special, or multi-episode selection. A caller MAY request a stem without an extension. The profile SHALL NOT assume MKV.

#### Scenario: Request multiple container extensions
- **WHEN** callers request the same entity with `mkv`, `mp4`, and `webm`
- **THEN** each response uses the requested validated extension while preserving the same directory and basename

#### Scenario: Request an extensionless stem
- **WHEN** a caller omits the target extension
- **THEN** the response contains directory and basename without inventing an extension

#### Scenario: Name multiple episodes
- **WHEN** a selection covers season 1 episodes 1 and 2
- **THEN** the basename contains the deterministic range `S01E01-E02`

#### Scenario: Reject a non-contiguous episode selection
- **WHEN** a selection contains episodes 1 and 3 but not episode 2
- **THEN** the system returns a stable validation error rather than widening it to the inclusive range `S01E01-E03`

### Requirement: Safe portable paths
Naming SHALL preserve Unicode while removing control characters, traversal components, Jellyfin-reserved characters, trailing unsafe characters, and platform-reserved names.

#### Scenario: Unsafe localized title
- **WHEN** title input contains Unicode plus traversal and reserved-name components
- **THEN** the resulting relative path retains safe Unicode and cannot escape its relative root or create a reserved path component

### Requirement: Versioned NFO endpoints
The system SHALL expose current NFO at `GET /api/v1/media-items/{id}/exports/nfo` and pinned NFO at `GET /api/v1/acquisitions/{id}/exports/nfo`. Query parameters SHALL identify `entity_type` as `movie`, `tvshow`, `season`, or `episode` and provide season and episode selectors when required. A successful response SHALL use an XML media type and SHALL include the recommended NFO filename in `Content-Disposition`.

#### Scenario: Request current TV show NFO
- **WHEN** an authenticated caller requests `entity_type=tvshow` for a series media item
- **THEN** the system returns XML from its current effective revision with the recommended `tvshow.nfo` filename

#### Scenario: NFO entity does not match media type
- **WHEN** a caller requests `entity_type=tvshow` for a movie
- **THEN** the API returns a stable validation error envelope instead of XML

### Requirement: Jellyfin and Kodi compatible NFO
The NFO endpoints SHALL emit well-formed XML 1.0 that is Jellyfin/Kodi-compatible for a movie, TV show, season, or one episode. They SHALL sanitize or reject XML 1.0-forbidden code points in every projected text and attribute. They SHALL include available provider IDs, titles, plot, dates, runtime, ratings, genres, tags, countries, studios, people, artwork URLs, and special ordering while omitting playback and user-state fields.

#### Scenario: Export a movie NFO
- **WHEN** rich effective movie metadata is requested
- **THEN** the response is escaped XML containing the available supported fields and recommended filename

#### Scenario: Export one special episode NFO
- **WHEN** a Season 00 episode is requested
- **THEN** the episode NFO identifies season zero and preserves special ordering metadata

### Requirement: Multi-episode NFO rejection
The system SHALL reject a single episode-NFO request for a multi-episode video with HTTP 422 and code `nfo_multi_episode_unsupported` while continuing to permit multi-episode naming.

#### Scenario: Request NFO for two episodes
- **WHEN** a caller requests one episode NFO for a selection spanning multiple episodes
- **THEN** the API returns 422 `nfo_multi_episode_unsupported` and recommends splitting the episodes
