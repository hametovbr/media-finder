## Why

Persisted integration settings make deployment state harder to understand and allow the UI and database to disagree with the container environment. Media Finder should use the deployment environment as the only source of truth for TMDB, Prowlarr, and the single MVP qBittorrent instance while making every module's required variables discoverable through its public contract.

## What Changes

- **BREAKING** Remove browser configuration and persisted runtime configuration for TMDB, Prowlarr, and qBittorrent.
- **BREAKING** Replace user-managed named download-client instances with one environment-owned qBittorrent instance for new acquisitions.
- Add a public environment-variable declaration to metadata-provider and download-client registrations. Each declaration includes the exact variable name, whether it is required, whether it is secret, and a localizable description key.
- Define the exact first-party variables: `TMDB_TOKEN`; `PROWLARR_URL` and `PROWLARR_API_KEY`; `QBITTORRENT_URL`, `QBITTORRENT_USERNAME`, and `QBITTORRENT_PASSWORD`.
- Keep the official TMDB API origin fixed in the TMDB module rather than exposing it as operator configuration.
- Make Settings a read-only integration diagnostic that reports declared variable names and safe `set`, `missing`, `ready`, or `unavailable` states without returning values.
- Preserve historical acquisitions and their referenced client rows while preventing legacy persisted client configuration from being selected for new submissions.
- Update Compose and operator documentation to describe environment-only configuration and container-restart semantics.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `module-contracts-and-retention`: Modules declare exact environment requirements and runtime construction no longer consumes persisted integration configuration.
- `torrent-acquisition`: New acquisitions use one environment-owned qBittorrent instance instead of user-managed named client instances.
- `bilingual-web-ui`: Settings becomes a read-only integration-status surface and no longer creates, edits, archives, or restores integration configuration.
- `deployment-and-delivery`: Deployment examples and operator behavior expose all first-party integration variables explicitly and apply changes after restart.

## Impact

The public module SDK and conformance fixtures change, as do runtime composition, Settings routes/templates, acquisition client resolution, database migration behavior for legacy client rows, localization catalogs, Compose examples, operator documentation, OpenAPI-visible diagnostics, and browser/integration/contract tests. No new service, queue, database, or runtime plugin loader is introduced.
