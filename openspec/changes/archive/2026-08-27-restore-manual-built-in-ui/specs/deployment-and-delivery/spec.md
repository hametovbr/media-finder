## MODIFIED Requirements

### Requirement: Single-process runtime
The default supported runtime SHALL use one application container, one web-server worker, separately buildable server-host, core, module-SDK, control-contract, built-in-UI, Manual, TMDB, Prowlarr, and qBittorrent packages, and a SQLite database in WAL mode under `/data`. It SHALL NOT require Redis, a queue, a separate worker container, a separate integration process, or a separate UI container.

#### Scenario: Start a normal deployment
- **WHEN** the service starts with writable `/data`, valid core configuration, and default UI mode
- **THEN** one application process serves the built-in UI, browser control API, processor API, and health endpoints, schedules generic in-process daily maintenance, and owns the lifecycle of statically registered modules

#### Scenario: Build workspace packages
- **WHEN** release automation builds the production artifact
- **THEN** it independently builds every workspace distribution and includes the selected modules plus the built-in UI's compiled browser output, localization resources, and deterministic static assets in the common image
