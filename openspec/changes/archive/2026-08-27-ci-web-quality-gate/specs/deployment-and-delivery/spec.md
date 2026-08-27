## MODIFIED Requirements

### Requirement: Reproducible quality gates
GitHub Actions SHALL run OpenSpec strict validation, documentation-policy checks, Python and built-in UI formatting and linting, type checks, the full built-in UI unit-test suite, isolated builds and import checks for every workspace package, dependency-architecture checks, module conformance, language-neutral schema and OpenAPI drift checks, unit, integration, gateway/API conformance, browser, and production-image tests as applicable to a change. These checks SHALL remain within the existing required `verification/*` check contexts unless repository protection is intentionally migrated.

#### Scenario: Behavior change lacks a valid spec
- **WHEN** a pull request changes behavior but strict OpenSpec validation fails
- **THEN** CI prevents the change from passing required checks

#### Scenario: Package violates dependency direction
- **WHEN** an integration imports core, core imports a concrete integration or built-in UI, built-in UI imports backend internals, or an isolated wheel relies on undeclared workspace source paths
- **THEN** CI prevents the change from passing required checks

#### Scenario: Built-in UI gains a backend dependency
- **WHEN** the UI package imports a prohibited backend internal or its checked-in control OpenAPI snapshot differs from the generated schema
- **THEN** CI prevents the change from passing required checks

#### Scenario: Built-in UI quality regression
- **WHEN** built-in UI source fails repository formatting or linting rules or any test in its full unit-test suite fails
- **THEN** CI prevents the change from passing required checks

#### Scenario: Public schema drifts
- **WHEN** a module manifest, SDK DTO, conformance fixture, control API, or processor API changes without an updated deterministic serialized artifact
- **THEN** CI prevents the change from passing required checks
