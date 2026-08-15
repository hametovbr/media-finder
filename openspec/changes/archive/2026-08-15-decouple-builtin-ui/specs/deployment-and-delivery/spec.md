## MODIFIED Requirements

### Requirement: Single-process runtime
The default supported runtime SHALL use one application container, one web-server worker, separately buildable backend, control-contract, and built-in-UI packages, and a SQLite database in WAL mode under `/data`. It SHALL NOT require Redis, a queue, a separate worker container, or a separate UI container.

#### Scenario: Start a normal deployment
- **WHEN** the service starts with writable `/data`, valid core configuration, and default UI mode
- **THEN** one application process serves the built-in UI, browser control API, processor API, and health endpoints and schedules generic in-process daily maintenance

#### Scenario: Build workspace packages
- **WHEN** release automation builds the production artifact
- **THEN** it independently builds the control-contract and built-in-UI packages and includes their templates, localization catalogs, and static assets in the common image

### Requirement: Reproducible quality gates
GitHub Actions SHALL run OpenSpec strict validation, documentation-policy checks, formatting, linting, type checks, independent control-contract and built-in-UI package builds, architecture-boundary checks, unit, integration, gateway/API conformance, OpenAPI drift, browser, and production-image tests as applicable to a change. These checks SHALL remain within the existing required `verification/*` check contexts unless repository protection is intentionally migrated.

#### Scenario: Behavior change lacks a valid spec
- **WHEN** a pull request changes behavior but strict OpenSpec validation fails
- **THEN** CI prevents the change from passing required checks

#### Scenario: Built-in UI gains a backend dependency
- **WHEN** the UI package imports a prohibited backend internal or its checked-in control OpenAPI snapshot differs from the generated schema
- **THEN** CI prevents the change from passing required checks

## ADDED Requirements

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
