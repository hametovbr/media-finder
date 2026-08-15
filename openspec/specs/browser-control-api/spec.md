# browser-control-api Specification

## Purpose
Define a stable same-origin browser control contract that lets the bundled interface and independently developed replacement interfaces use Media Finder without backend-internal dependencies.

## Requirements

### Requirement: Versioned browser control surface
The system SHALL expose a JSON browser control API under `/api/control/v1` and a deterministic OpenAPI document at `/api/control/openapi.json`. The API SHALL cover browser session preferences, collections, catalog items and details, metadata providers and search confirmation, Manual create/edit/import confirmation and episode CSV import, release search, live destinations, Acquisition submission and reconciliation, integration diagnostics, and attribution. Breaking wire changes SHALL use a new API version; fields added within version 1 SHALL remain backward-compatible.

#### Scenario: Generate an external UI client
- **WHEN** an interface developer consumes the checked-in control OpenAPI document
- **THEN** every supported browser control operation and its request, response, and error schemas are available without importing backend code

#### Scenario: Existing processor requests continue
- **WHEN** an integration calls an existing Bearer-protected `/api/v1/*` metadata or export endpoint
- **THEN** its route, authentication, response, and error contract remain unchanged by the browser control API

### Requirement: Stable control responses and errors
Control responses SHALL use versioned typed representations and SHALL NOT expose raw provider payloads, torrent artifacts, complete provider or download URLs, credentials, integration environment values, or the processor integration token. Failures SHALL return a stable language-neutral machine code, request ID, and safe details without localized prose.

#### Scenario: Upstream search fails with sensitive details
- **WHEN** a metadata provider, Prowlarr, or qBittorrent failure contains a credential or sensitive URL
- **THEN** the control response contains only a stable safe error and request ID and none of the sensitive value

#### Scenario: UI localizes a domain failure
- **WHEN** the built-in or replacement UI receives a known control error code
- **THEN** it selects its own localized message while retaining the unchanged machine code for diagnostics

### Requirement: Same-origin browser session
`GET /api/control/v1/session` SHALL create or continue the signed `mf_session` cookie and return a CSRF token, selected UI locale, selected metadata locale, and supported locales. `PATCH /api/control/v1/session` SHALL change supported locale preferences without creating user-account state. The cookie SHALL remain `HttpOnly`, `SameSite=Lax`, path `/`, and configurable as `Secure`.

#### Scenario: Bootstrap a new browser
- **WHEN** a browser without a valid session requests the session resource
- **THEN** the response creates a hardened signed cookie and returns a CSRF token without returning the signing secret

#### Scenario: Preserve independent metadata locale
- **WHEN** a user changes UI locale after explicitly selecting a metadata locale
- **THEN** the session retains the metadata locale independently and later provider operations use it

### Requirement: JSON mutation protection
Every mutating browser control request SHALL require `application/json`, a valid `X-CSRF-Token` matching the signed session, and a same-origin `Origin`. The application SHALL NOT enable cross-origin resource sharing for the control API. A valid CSRF token SHALL remain reusable within its unchanged session; opaque selection and confirmation tokens remain independently single-use.

#### Scenario: Reject a foreign origin
- **WHEN** a request supplies a valid session and CSRF token from an origin different from the effective Media Finder origin
- **THEN** the mutation is rejected with a stable safe error and no state change or cross-origin response permission

#### Scenario: Reuse a valid session token
- **WHEN** the same valid CSRF token protects multiple same-origin mutations in one unchanged session
- **THEN** each request is evaluated normally rather than treating the CSRF token as a one-use workflow token

#### Scenario: Reject a simple cross-site mutation
- **WHEN** a control mutation omits JSON media type or the CSRF header
- **THEN** the system rejects it before applying domain behavior

### Requirement: Bounded catalog resources
Every list response SHALL accept an optional opaque continuation cursor and a `limit` whose default is 50 and maximum is 100. A response SHALL contain `items` and a nullable `next_cursor`. A cursor SHALL be bound to its endpoint, filters, ordering, and position and SHALL be rejected if it is altered or reused with different query semantics.

#### Scenario: Continue a catalog page
- **WHEN** more media items exist than the requested limit
- **THEN** the response returns at most that limit plus an opaque cursor that continues the same stable ordering without repeating an item

#### Scenario: Tamper with a cursor
- **WHEN** a caller changes an opaque cursor or submits it under different filters
- **THEN** the API returns a stable validation error without exposing cursor contents

### Requirement: Opaque workflow tokens
Metadata results, Manual duplicate confirmations, release results, and other unsafe intermediate workflow state SHALL remain in bounded process-memory TTL stores owned by the backend. The browser SHALL receive cryptographically opaque tokens. A consumed, expired, evicted, or restart-invalidated token SHALL return HTTP 410 with code `selection_expired` and SHALL require the originating operation to be repeated.

#### Scenario: Confirm a metadata result once
- **WHEN** a caller successfully consumes a metadata selection token
- **THEN** the selected item operation occurs at most once and a second consumption returns `selection_expired`

#### Scenario: Process restarts before confirmation
- **WHEN** the application restarts after issuing an unconsumed workflow token
- **THEN** the old token is invalid and no sensitive intermediate state was persisted

### Requirement: Catalog and metadata control workflows
The control API SHALL preserve provider-scoped identity, immutable revision, explicit similarity confirmation, lossless Manual editing, atomic Manual import, and locale behavior defined by the catalog capability. Exact duplicates SHALL return the existing item. Similar cross-provider matches and an existing Manual identity SHALL require an explicit opaque confirmation before creating a separate item or revision.

#### Scenario: Add a provider result
- **WHEN** a caller confirms a valid metadata selection that is neither an exact duplicate nor an unconfirmed similar item
- **THEN** the API returns the saved item and its immutable current revision without exposing provider raw data

#### Scenario: Import an existing Manual identity
- **WHEN** a complete Manual version-1 document targets an existing Manual UUID without a valid confirmation
- **THEN** the API returns a confirmation-required result and creates no revision

#### Scenario: Import one invalid episode row
- **WHEN** any row in a bounded CSV episode import is invalid
- **THEN** the API applies none of the rows and returns a stable safe validation error

### Requirement: Acquisition control workflows
The control API SHALL preserve explicit torrent selection, live environment-owned qBittorrent destination selection, idempotent submission, exact correlation, bounded Acquisition states, secret-safe release snapshots, timeout recovery, and manual reconciliation. Release tokens SHALL remain one-use even when resolution or submission fails.

#### Scenario: Submit a selected release
- **WHEN** a caller supplies a valid release token, current destination, and idempotency key
- **THEN** the API returns the existing or newly created Acquisition and creates at most one qBittorrent task

#### Scenario: Reconcile without Prowlarr
- **WHEN** a pending Acquisition is manually reconciled while Prowlarr is unavailable
- **THEN** the API uses exact qBittorrent correlation and does not require release search or Prowlarr access

### Requirement: Safe integration diagnostics
The control API SHALL expose installed integration declarations, exact environment-variable names, required and secret classifications, safe set or missing state, readiness state, and provider attribution without returning environment values, value lengths, hashes, partial masks, credentials, or upstream response bodies.

#### Scenario: Inspect a configured secret
- **WHEN** a diagnostic describes a set secret environment variable
- **THEN** the response identifies its name and secret classification but reveals no property of its resolved value beyond being set

### Requirement: Same-origin replacement interface
An independently implemented interface SHALL be supported when it is served under the same browser origin and consumes only the documented control API. Network exposure SHALL require external reverse-proxy authentication, and a replacement interface SHALL NOT require the processor integration token.

#### Scenario: Route an external interface through a reverse proxy
- **WHEN** a reverse proxy sends `/` to an external frontend and `/api/control`, `/api/v1`, and `/health` to Media Finder under one origin
- **THEN** the frontend can bootstrap a browser session and use the control API without CORS or a processor token
