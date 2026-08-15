## Why

The built-in Jinja/HTMX interface currently creates database and integration infrastructure and calls backend repositories and domain services directly, so it cannot be developed, tested, or replaced independently. Media Finder needs a stable browser-facing control boundary while retaining the current one-container experience and existing HTML workflows.

## What Changes

- Add a versioned same-origin browser control API at `/api/control/v1` for catalog, metadata, Manual, acquisition, diagnostics, and browser-session workflows.
- Add framework-independent typed control contracts and an asynchronous gateway implemented by the backend and consumed by both the HTTP adapter and built-in UI.
- Move the built-in Jinja/HTMX interface into a separately buildable monorepo package that depends only on the control contracts and web-presentation libraries.
- Preserve every current HTML route, form workflow, English/Russian localization behavior, accessibility contract, signed `mf_session` cookie, and processor `/api/v1/*` contract.
- Add a deterministic fake gateway and UI development host that require no database or external integrations.
- Add `MEDIA_FINDER_UI_MODE=builtin|disabled`; `builtin` remains the default and `disabled` leaves control, processor, health, and maintenance behavior available.
- Document an optional same-origin external-UI topology without shipping another frontend, image, repository, cross-origin mode, user system, or runtime UI plugin loader.

## Capabilities

### New Capabilities

- `browser-control-api`: Versioned typed browser API, session and CSRF security, safe control-plane resources, bounded opaque tokens, compatibility, and external-UI consumption.

### Modified Capabilities

- `bilingual-web-ui`: The existing interface becomes a separately buildable built-in package that consumes only the control contract while preserving its routes and behavior.
- `deployment-and-delivery`: The default image still serves one-container UI and APIs, supports disabling only the built-in UI, and verifies independent package builds and same-origin replacement topology.

## Impact

The Python and pnpm project become workspaces containing the backend, control-contract, and built-in-UI packages. Runtime composition, browser security, control use cases, OpenAPI output, templates, static assets, gettext catalogs, UI tests, CI package gates, image smoke tests, Compose documentation, operator guidance, and `AGENTS.md` import rules change. The SQLite schema, stored data, processor Bearer API, external integration contracts, acquisition semantics, and default container topology remain compatible.
