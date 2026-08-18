# Deployment and Delivery Specification

## Purpose

Define a compact, reproducible deployment and release contract suitable for self-hosted operation without assumptions about private infrastructure.

## Requirements

### Requirement: Single-process runtime
The default supported runtime SHALL use one application container, one web-server worker, separately buildable server-host, core, module-SDK, control-contract, built-in-UI, Manual, TMDB, Prowlarr, and qBittorrent packages, and a SQLite database in WAL mode under `/data`. It SHALL NOT require Redis, a queue, a separate worker container, a separate integration process, or a separate UI container.

#### Scenario: Start a normal deployment
- **WHEN** the service starts with writable `/data`, valid core configuration, and default UI mode
- **THEN** one application process serves the built-in UI, browser control API, processor API, and health endpoints, schedules generic in-process daily maintenance, and owns the lifecycle of statically registered modules

#### Scenario: Build workspace packages
- **WHEN** release automation builds the production artifact
- **THEN** it independently builds every workspace distribution and includes the selected modules plus built-in UI templates, localization catalogs, and static assets in the common image

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
GitHub Actions SHALL run OpenSpec strict validation, documentation-policy checks, formatting, linting, type checks, isolated builds and import checks for every workspace package, dependency-architecture checks, module conformance, language-neutral schema and OpenAPI drift checks, unit, integration, gateway/API conformance, browser, and production-image tests as applicable to a change. These checks SHALL remain within the existing required `verification/*` check contexts unless repository protection is intentionally migrated.

#### Scenario: Behavior change lacks a valid spec
- **WHEN** a pull request changes behavior but strict OpenSpec validation fails
- **THEN** CI prevents the change from passing required checks

#### Scenario: Package violates dependency direction
- **WHEN** an integration imports core, core imports a concrete integration or built-in UI, built-in UI imports backend internals, or an isolated wheel relies on undeclared workspace source paths
- **THEN** CI prevents the change from passing required checks

#### Scenario: Built-in UI gains a backend dependency
- **WHEN** the UI package imports a prohibited backend internal or its checked-in control OpenAPI snapshot differs from the generated schema
- **THEN** CI prevents the change from passing required checks

#### Scenario: Public schema drifts
- **WHEN** a module manifest, SDK DTO, conformance fixture, control API, or processor API changes without an updated deterministic serialized artifact
- **THEN** CI prevents the change from passing required checks

### Requirement: Lockstep workspace release
All workspace distributions SHALL use one dependency lock and one product release version and SHALL be assembled into the existing production image. Module manifests SHALL still declare module version and SDK compatibility for machine-readable contract checking, but the MVP SHALL NOT publish independently versioned module release trains or require a package registry at runtime.

#### Scenario: Publish a product release
- **WHEN** release automation publishes a Media Finder version
- **THEN** the server host, core, contracts, built-in UI, and first-party module wheels are built from the same commit and product version before the image is published

#### Scenario: Install the production host
- **WHEN** the server-host wheel is installed in an isolated production environment
- **THEN** all runtime packages resolve from the locked workspace build and the process does not import source directories outside installed distributions

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

### Requirement: Configurable log level
The application SHALL read `MEDIA_FINDER_LOG_LEVEL` once at process construction. It SHALL accept only `debug`, `info`, `warning`, `error`, and `critical` case-insensitively, default to `info`, and fail startup safely for any other value. The selected level SHALL apply to the root logger and to the Uvicorn access and error logs.

#### Scenario: Default log level
- **WHEN** the process starts without `MEDIA_FINDER_LOG_LEVEL`
- **THEN** the application and Uvicorn logs emit at the `info` level

#### Scenario: Select a log level
- **WHEN** the process starts with `MEDIA_FINDER_LOG_LEVEL=debug` in any letter case
- **THEN** `debug` and higher messages appear in the application and Uvicorn logs for the single worker

#### Scenario: Reject an invalid log level
- **WHEN** the process starts with an unsupported `MEDIA_FINDER_LOG_LEVEL` value
- **THEN** startup fails with a safe configuration error before the web server begins accepting requests

### Requirement: External same-origin deployment guidance
Operator documentation SHALL describe an optional reverse-proxy topology in which an external interface serves `/` and Media Finder serves `/api/control`, `/api/v1`, and `/health` under the same origin. It SHALL require the same external authentication policy for the interface and control API and SHALL NOT instruct operators to enable CORS or expose a processor token to the browser.

#### Scenario: Inspect replacement-UI guidance
- **WHEN** an operator prepares an external interface deployment
- **THEN** the documentation identifies route ownership, authentication boundaries, default one-container behavior, disabled-mode rollback, and the absence of a supported cross-origin mode

### Requirement: Repository-owned agent workflow
The repository SHALL contain a self-sufficient project skill catalog for OpenSpec planning and apply, architecture decisions, implementation, debugging, review, public-contract evolution, module authoring, verification, publication, stable release, and skill maintenance. `AGENTS.md` SHALL retain project invariants and route work to those project-local skills without requiring a user-level skill installation or a specific workstation path.

#### Scenario: Continue work on another device
- **WHEN** a contributor or supported coding agent opens a clean repository checkout on another device
- **THEN** the checked-in `AGENTS.md` and `.agents/skills` provide the Media Finder-specific workflow, decision boundaries, and completion criteria without reading files from the previous device

#### Scenario: External skill is also installed
- **WHEN** a user-level skill overlaps a project-local Media Finder workflow
- **THEN** repository invariants and the project-local skill govern the project-specific procedure while system, developer, and explicit user instructions retain their normal precedence

### Requirement: Pressure-tested skill behavior
Each manually maintained project skill SHALL be concise, trigger-specific, and validated with a realistic application or pressure scenario. A new or materially changed skill SHALL have observed behavior without the target guidance and a repeated scenario with the target guidance explicitly applied. The evaluation record SHALL identify system, developer, global-skill, repository-instruction, project-skill, tool, workspace, and conversation context that the harness can expose.

An evaluation SHALL distinguish a historical observed RED, an isolated no-guidance baseline, a no-target-skill control, a contaminated control with overlapping guidance, and a post-skill forward test. A fresh conversation or omitted conversation fork SHALL NOT be described as isolated when other instruction sources remain available. A control that already complies SHALL be recorded as such rather than relabeled or repeatedly altered to manufacture failure. Literal source-text checks SHALL NOT substitute for behavioral evaluation, and contaminated controls SHALL NOT support causal claims beyond the behavior actually observed.

#### Scenario: Add a discipline skill
- **WHEN** a project skill is introduced to prevent architecture or workflow shortcuts under delivery pressure
- **THEN** its evidence records the historical or current control choice and rationalization, available instruction sources, the same scenario with the skill explicitly applied, observable decisions that distinguish compliance, and any limitation on attributing the result to that skill

#### Scenario: Fresh subagent can see overlapping guidance
- **WHEN** a pressure scenario uses a fresh conversation or omits parent conversation turns but the agent can still access global skills, repository instructions, project files, or the shared workspace
- **THEN** the run is labeled a contaminated or no-target-skill control rather than an isolated baseline, and a correct answer is not claimed as proof that the new skill caused the behavior

#### Scenario: Control already complies
- **WHEN** a no-target-skill control makes the expected decision without the new skill
- **THEN** the result is recorded honestly, historical observed RED may supply the failure evidence, and the scenario is not manipulated merely to obtain a failing answer

#### Scenario: Maintain generated OpenSpec skills
- **WHEN** the pinned OpenSpec CLI changes generated lifecycle skills
- **THEN** the repository regenerates and validates them through the CLI rather than editing their generated bodies manually

### Requirement: Reusable manually maintained guidance
Each manually maintained project skill and permanent routing rule SHALL express reusable decision conditions and procedures rather than hard-code the product version, release tag, workstation path, selected implementation, or historical incident current when the guidance was written. Release identifiers and incident-specific details MAY appear in release plans, change tasks, reference documentation, and labeled pressure scenarios, but SHALL NOT define a skill's purpose, trigger, or universal workflow. A release skill SHALL derive the intended version and tags from the approved release context and checked-in repository state.

#### Scenario: Use publication guidance for a later release
- **WHEN** a contributor invokes the publication skill for an approved future product release
- **THEN** the skill derives the intended version, previous tag, target commit, and moving tags from current repository and release context without requiring edits to replace an embedded earlier release number

#### Scenario: Learn from a historical auxiliary-tool failure
- **WHEN** a past custom-parser escalation is used to evaluate pragmatic architecture guidance
- **THEN** the incident remains a labeled example or pressure scenario while the skill applies the general complexity-rung, ownership, direct-execution, and subtraction rules to other auxiliary mechanisms as well

### Requirement: Exact-commit verification and release handoff
Project publication guidance SHALL bind local evidence, pull-request checks, merge, version preparation, GitHub Release creation, and GHCR publication to explicit commit identities. Unavailable local tools, a dirty worktree, a changed HEAD, a failed or skipped required check, or an unverified release workflow SHALL be reported and SHALL NOT be described as a complete release.

#### Scenario: Prepare a stable release after merge
- **WHEN** all change and release-preparation pull requests are merged to `main`
- **THEN** the release is created from the exact verified lockstep-version commit only after all seven required checks and the main-branch publish for that commit succeed

#### Scenario: Publish an immutable stable tag
- **WHEN** a stable GitHub Release is published
- **THEN** the agent waits for the release workflow and verifies the immutable SemVer tag, moving minor tag, `latest`, expected multi-architecture manifest, release URL, commit SHA, and clean final worktree before declaring completion
