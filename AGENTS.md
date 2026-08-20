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

Approval is retrospective: only a user message received after the planning
artifacts were presented can authorize implementation. Requests such as
"build", "fix", or "start implementation" cannot pre-approve artifacts that do
not yet exist. Proposal, update, and apply are terminal for the current user
turn; never chain proposal into apply or apply into archive. A completed apply
reports status and stops. Archive requires a separate user request and may
perform only the inline sync required by its own workflow.

### Work-item completion

Phase completion is not overall work completion. A terminal OpenSpec handoff
MUST report the phase completed, the overall work status, and the next required
action or authorization. Until every applicable gate below succeeds, overall
work remains incomplete or blocked and MUST NOT be described as complete:

1. approved implementation and pre-archive verification;
2. canonical specification synchronization for every applicable delta;
3. archive of every completed active change;
4. one cohesive squashed commit or a small set of logically separated commits;
5. exact-candidate local verification and a clean worktree;
6. push of a non-`main` branch and creation of a pull request;
7. successful required checks and review for the exact pull-request head;
8. merge of that verified result and confirmation that the delivered result is
   present on `main`.

Do not finalize or publish a delivery commit that omits an applicable canonical
specification synchronization or archive. When delta specs exist, selecting an
archive path that skips synchronization cannot satisfy overall completion.
After a separately authorized archive succeeds, continue the already requested
commit, push, pull-request, check, review, and merge sequence without another
completion handoff unless the user narrows or stops it or an external gate
blocks progress.

For a behavior-neutral change that legitimately bypasses OpenSpec, report
OpenSpec closure as not applicable rather than silently omitting it. Commit,
push, pull-request verification, merge, and post-merge confirmation remain
mandatory. Failed, pending, skipped, stale-SHA, unavailable, or unconfirmed
evidence is blocking evidence, never a pass.

Direct OpenSpec CLI commands do not replace lifecycle skills. Before creating or
revising each planning artifact, fetch and follow its current
`openspec instructions <artifact> --change <name> --json` response. Treat
`skip_specs` and other workflow metadata as reviewed planning decisions: record
their justification in the artifacts and obtain later approval before apply.
Never edit canonical specs during apply or use `openspec archive --yes` to bypass
archive assessment and user selection.

Project-local skills under `.agents/skills` are the self-contained Media Finder
workflow. Subject to system, developer, and explicit user instructions, use them
before overlapping workstation-local skills. A clean checkout must be sufficient;
never depend on a personal skill path or installation.

## Project skill routing

| Work | Required project skill |
|---|---|
| Architecture, ownership, compatibility, or increased complexity | `making-pragmatic-media-finder-decisions` |
| Implementing an approved change or moving a business path | `developing-media-finder-changes` |
| Test, CI, packaging, migration, browser, image, or runtime failure | `debugging-media-finder-failures` |
| Design, implementation, PR, auxiliary mechanism, or release review | `reviewing-media-finder-changes` |
| API, SDK, schema, manifest, bound, error, or serialized-contract change | `evolving-media-finder-contracts` |
| Metadata provider | `adding-metadata-provider` |
| Release provider | `adding-release-provider` |
| Download client | `adding-download-client` |
| Normalized metadata or stored schema evolution | `evolving-metadata-schema` |
| Creating, editing, routing, or evaluating project skills | `maintaining-media-finder-skills` |
| Verification, commit, PR, merge, image publication, or stable release | `verifying-and-publishing-media-finder` |

Use the applicable OpenSpec lifecycle skill together with the routed skill. The
OpenSpec skills are generated and never manually edited.

## Complexity and compatibility circuit breaker

Use the lowest sufficient rung:

`configuration → script/adapter → module → package → process/service`

If implementation crosses an approved rung, adds an owner or business path, or
expands public scope, stop apply. Use `openspec-update-change`, compare simpler
alternatives, and obtain renewed approval; earlier apply authorization no longer
covers the escalated design. Prefer direct execution or maintained structured
tools over interpreting source text. Custom parsers, interpreters, platforms, or
services for auxiliary work require their own approved requirement and ownership
decision.

Every test must trace to an approved scenario or a reproduced defect in approved
behavior. Mutation tests do not create requirements. Before preserving or
breaking compatibility, inspect actual users, stored data, external consumers,
published contracts, and rollout coordination; neither answer is assumed.

During `openspec-apply-change`, use test-driven development for every behavior or contract change:

1. Add or update a focused test that expresses the approved requirement.
2. Run it and record the expected RED failure.
3. Implement the minimum production change.
4. Run focused tests to GREEN.
5. Run the relevant regression and repository verification gates.

If implementation exposes a missing or incorrect requirement or design decision, stop implementation and use `openspec-update-change`. Do not silently change scope, defer specified behavior, or modify planning artifacts ad hoc.

Before handoff, run `pnpm spec:validate` plus the format, lint, type, test, and production-build commands documented for the current project stage. Preserve the originating command's exit status when filtering output; use `pipefail` or avoid pipelines. Report any unavailable gate as `not run` or `blocked`, never passed.
