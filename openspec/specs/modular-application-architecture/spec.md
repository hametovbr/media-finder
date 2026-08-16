# Modular Application Architecture Specification

## Purpose

Define enforceable ownership, dependency, composition, and portability boundaries for Media Finder as a statically assembled modular monolith.

## Requirements

### Requirement: Package-enforced modular monolith
The system SHALL be assembled from separately buildable server-host, core, module-SDK, control-contract, built-in-UI, and first-party integration packages. The server host SHALL be the only package that depends on core, the selected concrete integration packages, and the optional built-in UI together. Core SHALL depend only on public contracts rather than concrete integration or UI packages; integration packages SHALL depend only on the module SDK and their implementation libraries; and the built-in UI SHALL depend only on control contracts and presentation libraries.

#### Scenario: Build packages independently
- **WHEN** CI builds each workspace distribution in an isolated environment
- **THEN** every distribution builds and imports using only its declared dependencies before the server host assembles them into the common image

#### Scenario: Introduce a forbidden dependency
- **WHEN** core imports a concrete first-party integration, an integration imports core or persistence, or the built-in UI imports core or an integration
- **THEN** an automated architecture check fails the required verification workflow

### Requirement: Core-owned business and persistence boundaries
Core SHALL exclusively own catalog and metadata invariants, acquisition state and idempotency, exports, transactions, database schema and migrations, opaque-token lifecycle, browser and processor application orchestration, maintenance scheduling, secret resolution, safe public error translation, and module lifecycle. Modules SHALL propose typed data or external effects through their capability contract and SHALL NOT receive database sessions, ORM records, repositories, application containers, HTTP routers, templates, framework request objects, or mutable core domain objects.

#### Scenario: Persist module output
- **WHEN** a module returns metadata, release information, a download result, or a retention action
- **THEN** core validates the public DTO, applies core invariants, owns the transaction, and persists only core-owned records

#### Scenario: Module requests application internals
- **WHEN** a module imports or requires a core repository, ORM type, route, template, or application service
- **THEN** its architecture or conformance verification fails before it can be included in the production image

### Requirement: Explicit bounded-context ownership
Core SHALL organize catalog and metadata, acquisition, exports, module runtime, control orchestration, and platform concerns as explicit bounded contexts with public application ports. A context SHALL exchange stable identifiers, immutable values, or declared ports with another context and SHALL NOT use another context's ORM implementation or mutate another context's records directly.

#### Scenario: Acquisition reads catalog state
- **WHEN** acquisition validates a media item and pinned metadata revision
- **THEN** it uses a catalog read port and retains scalar identifiers rather than importing catalog persistence models or traversing cross-context ORM relationships

#### Scenario: Export reads acquisition and metadata
- **WHEN** a processor export is requested
- **THEN** the export use case reads the required snapshots through core application ports and does not expose ORM records or provider raw payloads

### Requirement: Single composition and lifecycle owner
One server composition root SHALL construct the database resources, core application services, bounded caches, registered modules, browser security, HTTP adapters, maintenance runner, and optional built-in UI. One root lifespan SHALL start resources in dependency order and close them in reverse order. Child packages SHALL NOT create or close shared application infrastructure implicitly.

#### Scenario: Start the default application
- **WHEN** the production process starts in built-in UI mode
- **THEN** the composition root creates one coherent resource graph used by health, control, processor, maintenance, modules, and the UI

#### Scenario: Module construction fails
- **WHEN** a module fails configuration validation or live construction after allocating resources
- **THEN** the root-owned module lifecycle closes only resources from that failed attempt and leaves previously successful unrelated resources usable

### Requirement: Language-neutral semantic contracts
Public module DTOs, module manifests, browser control endpoints, processor endpoints, stable errors, and conformance fixtures SHALL have deterministic serialized contract artifacts suitable for an implementation in another language. The Python SDK and Pydantic models SHALL be one binding of those semantic contracts rather than the only compatibility definition. Artifact generation SHALL be deterministic and checked for drift in CI.

#### Scenario: Regenerate public contracts
- **WHEN** CI generates module JSON Schemas and HTTP OpenAPI documents from the approved source contracts
- **THEN** the generated content is byte-stable after canonicalization and matches the checked-in artifacts

#### Scenario: Implement a contract outside Python
- **WHEN** a future implementation consumes the published schemas, manifests, fixtures, and error definitions
- **THEN** it can execute the same conformance scenarios without importing Media Finder's Python core or preserving its internal Python module paths

### Requirement: Static trusted extension model
All production modules SHALL be reviewed build-time dependencies registered explicitly by the server host and released in the common image. The application SHALL NOT discover, install, update, hot-load, or execute arbitrary modules at runtime, and SHALL NOT provide module-defined routes, background workers, database migrations, HTML, JavaScript, or generic lifecycle hooks.

#### Scenario: Assemble first-party modules
- **WHEN** the production image is built
- **THEN** Manual, TMDB, Prowlarr, and qBittorrent are included through the same public manifest, registration, and conformance mechanisms available to repository-contributed modules

#### Scenario: Supply an unregistered module
- **WHEN** files or packages appear at runtime without an explicit host registration
- **THEN** the application ignores them and does not execute their code
