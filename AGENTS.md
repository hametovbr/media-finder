# Agent instructions

## Repository rules

- Write repository documentation and developer-facing prose in English. Russian is limited to localization catalogs, localization tests, and user metadata fixtures.
- Treat `openspec/` as the source of truth for behavior, UX, architecture, APIs, schemas, and module contracts.
- Keep Media Finder a catalog and acquisition control plane. It does not scan, mux, move, or monitor media files and does not invoke Jellyfin.
- Keep secrets in environment variables and redact secrets and sensitive URLs from errors and logs. First-party integrations declare exact environment variables and never persist integration values or environment references.
- Keep `packages/builtin-ui` dependent only on `media-finder-control-contracts` and presentation-layer libraries. It must not import the backend package, SQLAlchemy, persistence models, repositories, runtime composition, or integration modules.
- Treat `/api/control/v1` as the only supported boundary for an external browser UI. Any control-contract change requires an OpenSpec change, an updated deterministic OpenAPI snapshot, gateway/HTTP conformance tests, and browser-security tests.

## Modular package and module rules

The root is a virtual uv workspace. The server host (`apps/server`) is the only
concrete composition root: it may depend on core, control contracts, the built-in
UI, and selected first-party modules. Core depends only on the module SDK and
control contracts; a module wheel depends only on `media-finder-module-sdk` and
its own implementation libraries; the built-in UI depends only on control
contracts and presentation libraries. Do not introduce core-to-module imports,
module-to-core/persistence imports, UI-to-backend imports, or compatibility
shims; `tests/architecture/test_package_boundaries.py` enforces this graph.

Modules are trusted, reviewed, static build-time dependencies. Add them as one
workspace wheel under `packages/modules/<kind-name>/` with a public typed
`registration()`, `module.toml`, translations, and `fixtures/conformance.json`.
Register concrete modules explicitly in `apps/server/src/media_finder_server/modules.py`.
Do not add discovery, entry-point scanning, runtime installation, hot loading,
marketplaces, generic hooks, module routes, module migrations, module assets, or
a module service container. A second registration must not silently change the
explicit release/download selection.

`module.toml` is the value-free contract for identity, kind, version, SDK and
contract compatibility, capabilities, attribution, translation keys, and exact
environment declarations. Module factories receive only
`ResolvedModuleEnvironment`; modules do not read process-wide environment,
persist configuration or environment references, receive database/core/UI
objects, or disclose secrets. A module owns its transport and idempotent
`close()`; the root `ModuleRuntime` validates before caching, closes failed or
losing attempts, and the root lifespan closes shared resources in reverse order.

Keep executable SDK conformance and serialized conformance aligned. The former
uses the capability-specific `assert_*_registration_conforms` assertions; the
latter validates `fixtures/conformance.json` against
`schemas/module-sdk/v1/` without importing Python core. Update checked JSON
Schema/OpenAPI artifacts and deterministic validators with contract changes.
Serialized fixtures never contain credentials, magnets, torrent bytes,
authenticated URLs, or raw upstream payloads; executable fixtures may keep
bounded safe artifacts in memory.

## Spec-driven development

Every change that can affect runtime behavior, UX, architecture, APIs, schemas, module contracts, security, persistence, deployment, or operator behavior MUST follow the OpenSpec spec-driven development workflow.

Only behavior-neutral typo, comment, formatting, and safe repository-maintenance changes may bypass OpenSpec. If the impact is uncertain, use OpenSpec.

Use the installed OpenSpec skills as follows:

- `openspec-explore`: investigate a problem, clarify requirements, or compare approaches. It may read the codebase but must not implement behavior.
- `openspec-propose`: create a new change and all planning artifacts. This workflow is planning-only and must stop after presenting the artifacts for review.
- `openspec-update-change`: revise and reconcile planning artifacts for an existing active change when requirements, scope, design, or tasks change. It never edits implementation code.
- `openspec-apply-change`: implement an approved active change. Read every context file returned by OpenSpec, work task by task, and mark a task complete only after all of its specified behavior is implemented and verified.
- `openspec-sync-specs`: merge delta specifications into canonical `openspec/specs/` while intentionally keeping the change active.
- `openspec-archive-change`: finalize a completed change after implementation, verification, and specification synchronization.

Planning and implementation are separate authorization boundaries. Completing `openspec-propose` does not authorize implementation; implementation begins only through `openspec-apply-change` after the planning artifacts are approved.

During `openspec-apply-change`, use test-driven development for every behavior or contract change:

1. Add or update a focused test that expresses the approved requirement.
2. Run it and record the expected RED failure.
3. Implement the minimum production change.
4. Run focused tests to GREEN.
5. Run the relevant regression and repository verification gates.

If implementation exposes a missing or incorrect requirement or design decision, stop implementation and use `openspec-update-change`. Do not silently change scope, defer specified behavior, or modify planning artifacts ad hoc.

The project-specific skills `adding-metadata-provider`, `adding-release-provider`,
`adding-download-client`, and `evolving-metadata-schema` are additional domain
guardrails. Use them together with the applicable OpenSpec lifecycle skill; they
never replace proposal, apply, sync, or archive workflows. Update manifests,
executable and serialized conformance, deterministic artifacts, architecture
checks, and fixtures together with behavior.

Never edit generated `.agents/skills/openspec-*` files manually; regenerate them with the pinned OpenSpec CLI.

Before handoff, run `pnpm spec:validate` plus the format, lint, type, test, and production-build commands documented for the current project stage.
