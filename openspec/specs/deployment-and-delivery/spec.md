# Deployment and Delivery Specification

## Purpose

Define a compact, reproducible deployment and release contract suitable for self-hosted operation without assumptions about private infrastructure.

## Requirements

### Requirement: Single-process runtime
The default supported runtime SHALL use one application container, one web-server worker, separately buildable backend, control-contract, and built-in-UI packages, and a SQLite database in WAL mode under `/data`. It SHALL NOT require Redis, a queue, a separate worker container, or a separate UI container.

#### Scenario: Start a normal deployment
- **WHEN** the service starts with writable `/data`, valid core configuration, and default UI mode
- **THEN** one application process serves the built-in UI, browser control API, processor API, and health endpoints and schedules generic in-process daily maintenance

#### Scenario: Build workspace packages
- **WHEN** release automation builds the production artifact
- **THEN** it independently builds the control-contract and built-in-UI packages and includes their templates, localization catalogs, and static assets in the common image

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
The repository SHALL provide an infrastructure-neutral Compose example with one GHCR image, one named `/data` volume, a localhost-bound HTTP port by default, healthcheck, explicit environment placeholders, and non-root runtime. The placeholders SHALL include `TMDB_TOKEN`, `PROWLARR_URL`, `PROWLARR_API_KEY`, `QBITTORRENT_URL`, `QBITTORRENT_USERNAME`, and `QBITTORRENT_PASSWORD`. It SHALL contain no download/media mounts, private domains, proxy labels, authentication-provider assumptions, or private Docker-network names.

#### Scenario: Inspect the example deployment
- **WHEN** an operator reads the Compose example
- **THEN** they can identify every exact first-party integration variable and explicit customization points for port, bind volume, reverse proxy, and network without inheriting private infrastructure values

### Requirement: Environment-owned integration lifecycle
Operator documentation SHALL define the process environment as the only configuration source for TMDB, Prowlarr, and qBittorrent. A change to those variables SHALL take effect after recreating or restarting the application process and SHALL NOT require a database mutation.

#### Scenario: Change an integration variable
- **WHEN** an operator changes a declared integration variable and recreates the container
- **THEN** the application uses the new environment value and ignores any legacy persisted integration setting

#### Scenario: Roll back an integration change
- **WHEN** an operator restores the previous environment values and recreates the container
- **THEN** the previous integration configuration is restored without restoring the database

### Requirement: Backup and exposure guidance
Operator documentation SHALL require backing up `/data` before upgrades and external authentication before publishing the UI to a network.

#### Scenario: Prepare an upgrade
- **WHEN** an operator follows the documented upgrade procedure
- **THEN** they create a recoverable `/data` backup before starting the new image

### Requirement: Reproducible quality gates
GitHub Actions SHALL run OpenSpec strict validation, documentation-policy checks, formatting, linting, type checks, independent control-contract and built-in-UI package builds, architecture-boundary checks, unit, integration, gateway/API conformance, OpenAPI drift, browser, and production-image tests as applicable to a change. These checks SHALL remain within the existing required `verification/*` check contexts unless repository protection is intentionally migrated.

#### Scenario: Behavior change lacks a valid spec
- **WHEN** a pull request changes behavior but strict OpenSpec validation fails
- **THEN** CI prevents the change from passing required checks

#### Scenario: Built-in UI gains a backend dependency
- **WHEN** the UI package imports a prohibited backend internal or its checked-in control OpenAPI snapshot differs from the generated schema
- **THEN** CI prevents the change from passing required checks

### Requirement: Multi-architecture SemVer images
Release automation SHALL publish `linux/amd64` and `linux/arm64` GHCR images with immutable `vX.Y.Z`, moving `X.Y`, `latest` only for stable GitHub Releases, and `edge` for the main branch.

#### Scenario: Publish from main
- **WHEN** a successful main-branch build is not a stable GitHub Release
- **THEN** it may update `edge` but does not update `latest`

#### Scenario: Publish stable release
- **WHEN** a stable GitHub Release for `v1.2.3` succeeds
- **THEN** the same multi-architecture image is addressable by `v1.2.3`, `1.2`, and `latest`

### Requirement: Selectable built-in UI
The application SHALL read `MEDIA_FINDER_UI_MODE` once at process construction. It SHALL accept only `builtin` and `disabled`, default to `builtin`, and fail startup safely for any other value. Disabling the built-in UI SHALL omit its HTML and static routes while preserving the browser control API, processor API, health endpoints, storage, migrations, and maintenance in the same container.

#### Scenario: Disable the bundled interface
- **WHEN** the process starts with `MEDIA_FINDER_UI_MODE=disabled`
- **THEN** built-in HTML and static requests are not served while `/api/control/v1`, `/api/v1`, `/health/live`, and `/health/ready` remain available under their own authentication contracts

#### Scenario: Reject an invalid UI mode
- **WHEN** the process starts with an unsupported `MEDIA_FINDER_UI_MODE` value
- **THEN** startup fails with a safe configuration error before the web server begins accepting requests

### Requirement: External same-origin deployment guidance
Operator documentation SHALL describe an optional reverse-proxy topology in which an external interface serves `/` and Media Finder serves `/api/control`, `/api/v1`, and `/health` under the same origin. It SHALL require the same external authentication policy for the interface and control API and SHALL NOT instruct operators to enable CORS or expose a processor token to the browser.

#### Scenario: Inspect replacement-UI guidance
- **WHEN** an operator prepares an external interface deployment
- **THEN** the documentation identifies route ownership, authentication boundaries, default one-container behavior, disabled-mode rollback, and the absence of a supported cross-origin mode
