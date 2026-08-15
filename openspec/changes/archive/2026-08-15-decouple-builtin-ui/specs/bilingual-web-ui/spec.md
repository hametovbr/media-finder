## ADDED Requirements

### Requirement: Independently buildable built-in interface
The bundled interface SHALL be delivered as a separately buildable package that consumes only the public typed control contract and presentation libraries. It SHALL NOT require database, persistence-model, domain-service, runtime-integration, metadata-provider, download-client, or backend repository imports. A deterministic development mode SHALL render its critical workflows with fake control data and no database or external integration.

#### Scenario: Develop the interface in isolation
- **WHEN** a contributor starts the built-in UI development host without Media Finder storage or integration variables
- **THEN** the interface renders deterministic catalog, metadata, Manual, acquisition, diagnostics, English, and Russian states through the same control contract used in production

#### Scenario: Violate the package boundary
- **WHEN** built-in UI source imports a prohibited backend or integration package
- **THEN** an automated architecture check rejects the build

### Requirement: Built-in interface compatibility
The separately packaged built-in interface SHALL preserve all existing HTML routes, form actions, signed session behavior, localized feedback, accessibility semantics, and visible workflows when it is enabled. Moving behavior behind the control boundary SHALL NOT introduce a second domain path with different validation or persistence semantics.

#### Scenario: Use an existing bookmark and form workflow
- **WHEN** a user upgrades with the built-in UI enabled and opens or submits a previously supported HTML route
- **THEN** the route retains its method, result, locale behavior, and domain outcome

#### Scenario: Compare built-in and control behavior
- **WHEN** equivalent HTML and browser control requests exercise the same catalog, metadata, Manual, or acquisition operation
- **THEN** both use the same backend gateway and produce the same state transition and invariant machine error code
