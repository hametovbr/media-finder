## MODIFIED Requirements

### Requirement: Single-process runtime
The default supported runtime SHALL use one application container, one web-server worker, separately buildable server-host, core, module-SDK, control-contract, built-in-UI, Manual, TMDB, Prowlarr, and qBittorrent packages, and a SQLite database in WAL mode under `/data`. It SHALL NOT require Redis, a queue, a separate worker container, a separate integration process, or a separate UI container.

#### Scenario: Start a normal deployment
- **WHEN** the service starts with writable `/data`, valid core configuration, and default UI mode
- **THEN** one application process serves the built-in UI, browser control API, processor API, and health endpoints, schedules generic in-process daily maintenance, and owns the lifecycle of statically registered modules

#### Scenario: Build workspace packages
- **WHEN** release automation builds the production artifact
- **THEN** it independently builds every workspace distribution and includes the selected modules plus built-in UI templates, localization catalogs, and static assets in the common image

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

## ADDED Requirements

### Requirement: Lockstep workspace release
All workspace distributions SHALL use one dependency lock and one product release version and SHALL be assembled into the existing production image. Module manifests SHALL still declare module version and SDK compatibility for machine-readable contract checking, but the MVP SHALL NOT publish independently versioned module release trains or require a package registry at runtime.

#### Scenario: Publish a product release
- **WHEN** release automation publishes a Media Finder version
- **THEN** the server host, core, contracts, built-in UI, and first-party module wheels are built from the same commit and product version before the image is published

#### Scenario: Install the production host
- **WHEN** the server-host wheel is installed in an isolated production environment
- **THEN** all runtime packages resolve from the locked workspace build and the process does not import source directories outside installed distributions
