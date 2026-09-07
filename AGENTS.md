# Media Finder agent instructions

## Start with the task

1. Confirm the checkout, branch, diff, and applicable nested instructions. Preserve unrelated user work; isolate the candidate when necessary.
2. Identify the outcome, OpenSpec phase, and existing authorization. Read relevant canonical `openspec/specs/` and the selected active change; archives are historical evidence.
3. Load applicable lifecycle and project skills in full, then only the references needed for this task. Read every context file returned by OpenSpec. Reuse guidance while its contents and applicability remain current.

`openspec/` owns behavior, UX, architecture, APIs, schemas, and module contracts. Code/tests establish actual behavior; report conflicts instead of assuming alignment. This file owns stable invariants and routing; skills own conditional procedures; tests/CI enforce mechanical constraints.

Use project-local `.agents/skills/<name>/SKILL.md` before overlapping global skills, subject to system, developer, and explicit user instructions. Global skills may supplement missing expertise; they do not replace the lifecycle, add a competing plan, or authorize a transition. A clean checkout must suffice without personal skill paths, installed model profiles, or a specific harness.

## Repository map and invariants

- Write documentation and developer-facing prose in English. Russian is limited to localization catalogs, localization tests, and user metadata fixtures.
- Keep Media Finder a catalog and acquisition control plane. It does not scan, mux, move, or monitor media files and does not invoke Jellyfin.
- The root is a virtual uv workspace; `apps/server` is the only concrete composition root. Core depends only on the module SDK and control contracts; module wheels depend only on `media-finder-module-sdk` and implementation libraries; `packages/builtin-ui` depends only on control contracts and presentation libraries. No core-to-module, module-to-core/persistence, or UI-to-backend imports or compatibility shims. See `tests/architecture/test_package_boundaries.py` and `docs/architecture.md`.
- Modules are trusted static build-time dependencies under `packages/modules/<kind-name>/`, explicitly registered in `apps/server/src/media_finder_server/modules.py`. No discovery, runtime installation, hot loading, marketplaces, generic hooks, module routes/migrations/assets, or module service container. Additional registrations must not change explicit release/download selection. Follow `docs/module-authoring.md` for typed `registration()`, value-free `module.toml`, translations, and conformance fixtures.
- Keep secrets in environment variables; redact secrets and sensitive URLs. Modules receive only manifest-declared `ResolvedModuleEnvironment`, never process-wide environment access or core/database/UI objects. Never persist integration values or environment references. Follow `docs/module-authoring.md` for transport ownership, validation before caching, failed/losing-attempt cleanup, idempotent close, and reverse shutdown.
- `/api/control/v1` is the only supported external browser UI boundary. Control-contract changes require OpenSpec, deterministic OpenAPI, gateway/HTTP conformance, and browser-security tests. Keep runtime, executable/serialized conformance, schemas, fixtures, and validators aligned through `evolving-media-finder-contracts`. Follow `docs/module-authoring.md` for safe fixture content; never serialize credentials or sensitive acquisition/upstream artifacts.
- Edit browser source in `packages/builtin-ui/web`; regenerate packaged `static` assets and generated contracts through their owning tools. Never hand-edit generated `.agents/skills/openspec-*`; regenerate with the repository-pinned OpenSpec CLI.

Read `CONTRIBUTING.md` for setup/checks, `docs/operations.md` for deployment, and `SECURITY.md` for security findings, exceptions, and security-affecting delivery. Consult `docs/agent-skills.md` for provenance/evaluation evidence when needed, not on every task.

## OpenSpec lifecycle

Every change that can affect runtime behavior, UX, architecture, APIs, schemas, module contracts, security, persistence, deployment, or operator behavior MUST follow OpenSpec. Only behavior-neutral typo, comment, formatting, and safe repository-maintenance changes may bypass it. If impact is uncertain, use OpenSpec.

| Phase | Required lifecycle skill |
|---|---|
| Investigate or compare; no implementation | `openspec-explore` |
| Create planning artifacts; present for review and stop | `openspec-propose` |
| Revise existing scope, requirements, design, or tasks; planning only | `openspec-update-change` |
| Implement an approved active change, task by task | `openspec-apply-change` |
| Synchronize deltas while intentionally keeping the change active | `openspec-sync-specs` |
| Assess, synchronize, and archive verified completed work | `openspec-archive-change` |

Approval is retrospective: implementation requires a user message received after the planning artifacts were presented. A build/fix request cannot pre-approve artifacts that do not yet exist. Proposal, update, and apply are terminal for the current user turn; never chain proposal into apply or apply into archive. Report phase, overall status, and next required action or authorization. Archive requires a separate user request; its workflow may perform inline synchronization.

Direct OpenSpec CLI commands do not replace lifecycle skills. Before creating or revising each planning artifact, fetch and follow `openspec instructions <artifact> --change <name> --json`. Justify workflow metadata such as `skip_specs` in artifacts and obtain later approval before apply. Never edit canonical specs during apply or use `openspec archive --yes` to bypass assessment and user selection.

During apply, trace each test to an approved scenario or a reproduced defect in approved behavior: observe focused RED, implement the minimum change, verify GREEN, then run applicable regressions and repository gates. Mark tasks complete only after all specified behavior is implemented and verified. Mutation tests do not create requirements.

Use the lowest sufficient rung: `configuration → script/adapter → module → package → process/service`. A missing requirement/design decision, higher rung, new owner/business path, expanded public scope, or new compatibility obligation requires stopping apply, `openspec-update-change`, and renewed approval. Never silently defer behavior or edit plans ad hoc. Inspect actual users, stored data, consumers, published contracts, and rollout coordination before preserving or breaking compatibility. Custom auxiliary parsers, interpreters, platforms, or services need an approved requirement and ownership decision.

## Project skill routing

Use applicable project skills together with the lifecycle skill; do not load the entire catalog.

| Work | Required project skill |
|---|---|
| Architecture, ownership, compatibility, or increased complexity | `making-pragmatic-media-finder-decisions` |
| Approved implementation or moving a business path | `developing-media-finder-changes` |
| Test, CI, packaging, migration, browser, image, or runtime failure | `debugging-media-finder-failures` |
| Design, implementation, PR, auxiliary mechanism, or release review | `reviewing-media-finder-changes` |
| API, SDK, schema, manifest, bound, error, or serialized contract | `evolving-media-finder-contracts` |
| Metadata provider | `adding-metadata-provider` |
| Release provider | `adding-release-provider` |
| Download client | `adding-download-client` |
| Normalized metadata or stored schema evolution | `evolving-metadata-schema` |
| Creating, editing, routing, or evaluating project skills | `maintaining-media-finder-skills` |
| Verification, commit, PR, merge, image publication, or stable release | `verifying-and-publishing-media-finder` |

## Efficient execution

- Minimize total work and rework without weakening correctness, required reading, verification, or authorization. Use targeted `rg` searches and bounded output, retaining decisive evidence and full relevant errors. Batch independent reads; serialize dependent edits and shared Git/build resources.
- Use one agent for a small task. When delegation is authorized and useful, give each worker a bounded outcome, source paths, constraints, writable scope, checks, and stop conditions. Prefer task-local context; reuse workers for corrections; avoid recursive delegation. Parallelize only with independent interfaces/resources. Respect the available harness and authorized model/effort profile.
- Reuse checks only for the same candidate, command, dependencies, and relevant environment. Rerun affected checks after changes/failures and required final gates for the final candidate. Repeat optional tests/reviews for changed scope or unresolved findings, not by default.
- Prefer completion notifications or bounded waits to unchanged polling. Keep updates concise. For long work, keep one checkpoint with candidate, decisions, checks, unresolved items, and next action; reconcile it with actual state on resume. Do not add recurring administrative work or promise unmeasured token savings.

## Verification and execution environment

Run from the repository root. `CONTRIBUTING.md` and `.github/workflows/verify.yaml` define the full gates; `package.json`, `pyproject.toml`, and lockfiles define exact scripts and pinned tools. Do not invent commands or upgrade tools to fit a workflow.

- Setup: `pnpm install --frozen-lockfile`; `uv sync --frozen --all-groups`.
- Start: `pnpm spec:list` for active changes; `pnpm ui:dev` for the UI against fixtures.
- Documentation: `pnpm docs:check`; `pnpm spec:validate`.
- Python: `pnpm py:format`, `pnpm py:lint`, `pnpm py:type`, `pnpm py:test`.
- UI: `pnpm ui:format`, `pnpm ui:lint`, `pnpm ui:type`, `pnpm ui:test`, `pnpm ui:a11y`, `pnpm ui:browser`, `pnpm ui:contract`, `pnpm ui:build`.
- Delivery policy: `pnpm delivery:test`; `pnpm delivery:validate`.

Before handoff run `pnpm spec:validate` and the format, lint, type, test, production-build, and other gates applicable to the scope/current project stage. Follow `verifying-and-publishing-media-finder` for proportional local verification and every required PR check. Security-affecting delivery also requires the authenticated live check in `SECURITY.md`.

Before browser/socket/subprocess tests, wheel builds, dependency bootstrap, Docker, host-service observations, authenticated checks, or GitHub delivery, read `docs/agent-execution.md` and use the authorized execution boundary it specifies. Keep deterministic offline checks in the sandbox. Environment failures require supported-host evidence before product fixes; unavailable host access leaves the gate blocked. Repository instructions never grant permissions or bypass a denial.

Preserve command exit status: avoid output pipelines or use `pipefail`. Unavailable gates are `not run` or `blocked`, never passed. Never expose secrets or sensitive upstream payloads during diagnosis.

## Delivery and completion

Phase completion is not overall work completion. Until every applicable gate below succeeds, overall work remains incomplete or blocked:

1. approved implementation and pre-archive verification.
2. canonical specification synchronization for every applicable delta, and archive of every completed active change belonging to the delivered work.
3. one cohesive squashed commit or a small set of logically separated commits; exact-candidate local verification and a clean worktree.
4. push of a non-`main` branch and creation of a pull request.
5. successful required checks and review for the exact pull-request head.
6. merge of that verified result and confirmation that the delivered result is present on `main`.

Do not finalize/publish a delivery commit omitting applicable synchronization or archive; skipping synchronization cannot close a change with deltas. After separately authorized archive, continue the already requested commit, push, PR, check, review, and merge sequence unless the user narrows/stops it or an external gate blocks progress.

For legitimate behavior-neutral maintenance, report OpenSpec closure as not applicable; protected-branch delivery remains mandatory. Failed, pending, skipped, stale-SHA, unavailable, or unconfirmed required evidence blocks completion. Report phase/overall status, exact candidate, verification, PR/merge state, and unresolved next gate without reproducing full logs.
