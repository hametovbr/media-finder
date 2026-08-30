## MODIFIED Requirements

### Requirement: Versioned browser control surface
The system SHALL expose a JSON browser control API under `/api/control/v1` and a deterministic OpenAPI document at `/api/control/openapi.json`. The API SHALL cover browser session preferences, collections, catalog items and details, metadata providers and search confirmation, Manual create/edit/import confirmation and episode CSV import, release search, live destinations, Acquisition submission and reconciliation, integration diagnostics, and attribution. While the product has no released browser-control consumer other than the bundled interface, a contract change MAY update version 1 in place only when the checked-in OpenAPI document, generated bundled client, fixtures, and conformance and browser-security coverage are updated atomically. The system SHALL NOT add a compatibility shim, parallel route, or new API version solely for a hypothetical consumer.

#### Scenario: Generate an external UI client
- **WHEN** an interface developer consumes the checked-in control OpenAPI document
- **THEN** every supported browser control operation and its request, response, and error schemas are available without importing backend code

#### Scenario: Update the pre-public version-1 contract
- **WHEN** the only supported browser consumer and the version-1 response schema change together before public release
- **THEN** the deterministic OpenAPI document, generated bundled client, fixtures, conformance tests, and browser-security tests describe the same contract without retaining an obsolete compatibility path

#### Scenario: Existing processor requests continue
- **WHEN** an integration calls an existing Bearer-protected `/api/v1/*` metadata or export endpoint
- **THEN** its route, authentication, response, and error contract remain unchanged by the browser control API

### Requirement: Stable control responses and errors
Control responses SHALL use versioned typed representations and SHALL NOT expose raw provider payloads, torrent artifacts, authenticated or sensitive provider or download URLs, credentials, integration environment values, or the processor integration token. A metadata search result MAY expose the module-produced complete public poster URL defined by the metadata search-result contract and no other provider URL. Failures SHALL return a stable language-neutral machine code, request ID, and safe details without localized prose.

#### Scenario: Return a public search poster
- **WHEN** a validated metadata search result contains a module-produced complete poster URL
- **THEN** the control response may expose that exact public image URL without exposing an authenticated endpoint, credential, raw payload, or unrelated provider URL

#### Scenario: Upstream search fails with sensitive details
- **WHEN** a metadata provider, Prowlarr, or qBittorrent failure contains a credential or sensitive URL
- **THEN** the control response contains only a stable safe error and request ID and none of the sensitive value

#### Scenario: UI localizes a domain failure
- **WHEN** the built-in or replacement UI receives a known control error code
- **THEN** it selects its own localized message while retaining the unchanged machine code for diagnostics

## ADDED Requirements

### Requirement: Metadata search preview projection
Each successful result returned by `POST /api/control/v1/metadata-searches` SHALL include `description` as a nullable plain-text string and `poster_url` as a nullable complete URL in addition to its existing provider identity, media kind, title, year, and opaque selection token. Core SHALL defensively validate these optional values, retain them in the existing bounded ephemeral search state, and project them through control unchanged. When the module omits either field, control SHALL serialize its response key as null. Core and control SHALL NOT construct or rewrite a poster URL and SHALL NOT branch on a concrete metadata-provider identifier to provide previews.

#### Scenario: Project enriched metadata results
- **WHEN** a provider returns valid description and complete poster URL values for a metadata search result
- **THEN** the control response contains those exact values with the existing identity and selection token

#### Scenario: Serialize absent previews
- **WHEN** a provider omits one or both optional preview values
- **THEN** the control response retains the result and serializes each absent `description` or `poster_url` key as null

#### Scenario: Reject an unprotected metadata search
- **WHEN** a metadata-search mutation fails JSON, session, CSRF, or same-origin validation
- **THEN** the request is rejected before invoking a provider or creating search-cache or opaque-token state
