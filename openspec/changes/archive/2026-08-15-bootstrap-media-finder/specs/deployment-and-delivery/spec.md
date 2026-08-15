## Purpose

Define a compact, reproducible deployment and release contract suitable for self-hosted operation without assumptions about private infrastructure.

## ADDED Requirements

### Requirement: Single-process runtime
The supported runtime SHALL use one application container, one web-server worker, and a SQLite database in WAL mode under `/data`. It SHALL NOT require Redis, a queue, or a separate worker container.

#### Scenario: Start a normal deployment
- **WHEN** the service starts with writable `/data` and valid configuration
- **THEN** one application process serves the UI and API and schedules generic in-process daily maintenance

### Requirement: Migration-gated startup
Database migrations SHALL run before the web server. A migration failure or unavailable database SHALL stop the container.

#### Scenario: Migration fails
- **WHEN** a required migration cannot complete
- **THEN** the web server does not start and the container exits with an observable failure

### Requirement: Health contract
`/health/live` SHALL indicate process liveness without authentication. `/health/ready` SHALL require accessible storage and current migrations but SHALL NOT depend on external providers or clients.

#### Scenario: Prowlarr is unavailable
- **WHEN** local storage and migrations are healthy but Prowlarr is unreachable
- **THEN** readiness remains successful and integration status reports the upstream failure separately

### Requirement: Generic Compose example
The repository SHALL provide an infrastructure-neutral Compose example with one GHCR image, one named `/data` volume, a localhost-bound HTTP port by default, healthcheck, environment placeholders, and non-root runtime. It SHALL contain no download/media mounts, private domains, proxy labels, authentication-provider assumptions, or private Docker-network names.

#### Scenario: Inspect the example deployment
- **WHEN** an operator reads the Compose example
- **THEN** they can identify explicit customization points for port, bind volume, reverse proxy, and network without inheriting private infrastructure values

### Requirement: Backup and exposure guidance
Operator documentation SHALL require backing up `/data` before upgrades and external authentication before publishing the UI to a network.

#### Scenario: Prepare an upgrade
- **WHEN** an operator follows the documented upgrade procedure
- **THEN** they create a recoverable `/data` backup before starting the new image

### Requirement: Reproducible quality gates
GitHub Actions SHALL run OpenSpec strict validation, documentation-policy checks, formatting, linting, type checks, unit, integration, module-contract, browser, and production-image tests as applicable to a change.

#### Scenario: Behavior change lacks a valid spec
- **WHEN** a pull request changes behavior but strict OpenSpec validation fails
- **THEN** CI prevents the change from passing required checks

### Requirement: Multi-architecture SemVer images
Release automation SHALL publish `linux/amd64` and `linux/arm64` GHCR images with immutable `vX.Y.Z`, moving `X.Y`, `latest` only for stable GitHub Releases, and `edge` for the main branch.

#### Scenario: Publish from main
- **WHEN** a successful main-branch build is not a stable GitHub Release
- **THEN** it may update `edge` but does not update `latest`

#### Scenario: Publish stable release
- **WHEN** a stable GitHub Release for `v1.2.3` succeeds
- **THEN** the same multi-architecture image is addressable by `v1.2.3`, `1.2`, and `latest`
