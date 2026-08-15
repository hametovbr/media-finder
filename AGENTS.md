# Agent instructions

## Repository rules

- Write repository documentation and developer-facing prose in English. Russian is limited to localization catalogs, localization tests, and user metadata fixtures.
- Treat `openspec/` as the source of truth for behavior, UX, architecture, APIs, schemas, and module contracts.
- Keep Media Finder a catalog and acquisition control plane. It does not scan, mux, move, or monitor media files and does not invoke Jellyfin.
- Keep secrets in environment variables and redact secrets and sensitive URLs from errors and logs. First-party integrations declare exact environment variables and never persist integration values or environment references.
- Keep `packages/builtin-ui` dependent only on `media-finder-control-contracts` and presentation-layer libraries. It must not import the backend package, SQLAlchemy, persistence models, repositories, runtime composition, or integration modules.
- Treat `/api/control/v1` as the only supported boundary for an external browser UI. Any control-contract change requires an OpenSpec change, an updated deterministic OpenAPI snapshot, gateway/HTTP conformance tests, and browser-security tests.

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

The project-specific skills `adding-metadata-provider`, `adding-download-client`, and `evolving-metadata-schema` are additional domain guardrails. Use them together with the applicable OpenSpec lifecycle skill; they never replace proposal, apply, sync, or archive workflows. Update contracts, conformance tests, and fixtures together with behavior.

Never edit generated `.agents/skills/openspec-*` files manually; regenerate them with the pinned OpenSpec CLI.

Before handoff, run `pnpm spec:validate` plus the format, lint, type, test, and production-build commands documented for the current project stage.
