## MODIFIED Requirements

### Requirement: Generic Compose example
The repository SHALL provide an infrastructure-neutral Compose example with one GHCR image, one named `/data` volume, a localhost-bound HTTP port by default, healthcheck, explicit environment placeholders, and non-root runtime. The placeholders SHALL include `TMDB_TOKEN`, `PROWLARR_URL`, `PROWLARR_API_KEY`, `QBITTORRENT_URL`, `QBITTORRENT_USERNAME`, and `QBITTORRENT_PASSWORD`. It SHALL contain no download/media mounts, private domains, proxy labels, authentication-provider assumptions, or private Docker-network names.

#### Scenario: Inspect the example deployment
- **WHEN** an operator reads the Compose example
- **THEN** they can identify every exact first-party integration variable and explicit customization points for port, bind volume, reverse proxy, and network without inheriting private infrastructure values

## ADDED Requirements

### Requirement: Environment-owned integration lifecycle
Operator documentation SHALL define the process environment as the only configuration source for TMDB, Prowlarr, and qBittorrent. A change to those variables SHALL take effect after recreating or restarting the application process and SHALL NOT require a database mutation.

#### Scenario: Change an integration variable
- **WHEN** an operator changes a declared integration variable and recreates the container
- **THEN** the application uses the new environment value and ignores any legacy persisted integration setting

#### Scenario: Roll back an integration change
- **WHEN** an operator restores the previous environment values and recreates the container
- **THEN** the previous integration configuration is restored without restoring the database
