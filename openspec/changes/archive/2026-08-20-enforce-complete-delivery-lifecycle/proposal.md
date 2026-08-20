## Why

The repository distinguishes OpenSpec planning, implementation, verification, and archive authorization, but its current handoffs can describe an implementation phase as complete while specification sync, archive, commit, pull request checks, and merge still remain. This has already allowed required lifecycle work to be omitted or deferred without an unambiguous incomplete-task status.

## What Changes

- Define one repository-wide completion contract for OpenSpec changes and behavior-neutral maintenance work: phase completion is reportable, but the overall task remains incomplete until every applicable lifecycle and publication gate has finished.
- Require an OpenSpec change with delta specs to be verified, synchronized into canonical specs, and archived before its delivery commit is finalized; an archive that intentionally skips required synchronization cannot satisfy completion.
- Require intentional commit shaping into one cohesive squashed commit or a small set of commits separated by logical area, followed by branch push, pull request creation, exact-head required checks and review, and merge into `main`.
- Require post-merge evidence that the expected commit is present on `main`; failed, pending, skipped, stale-SHA, or unavailable evidence must be reported as blocked or incomplete rather than complete.
- Preserve retrospective planning/apply approval and terminal OpenSpec phase boundaries while making the remaining phase and its authorization need explicit at every handoff.
- Align project-owned agent guidance, skill evaluation records, and mechanical policy tests with the completion contract without modifying generated OpenSpec skill bodies.
- Restore executable Python verification by adopting Starlette's separately distributed `httpx2` test transport in the shared development and isolated built-in UI test environments, replacing the deprecated `httpx` fallback and its temporary warning exemptions.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-and-delivery`: strengthen repository-owned agent workflow and exact-commit publication requirements so overall work completion requires applicable OpenSpec closure, deliberate commits, pull-request verification, and confirmed merge into `main`.

## Impact

- Affected repository policy: `AGENTS.md` and project workflow documentation.
- Affected manually maintained skills: implementation handoff, review verdict, and verification/publication guidance under `.agents/skills/`.
- Affected validation: project-skill policy tests and skill-maintenance pressure-scenario evidence; existing GitHub required-check topology remains unchanged.
- Affected test tooling: root development dependencies, built-in UI isolated test dependencies, the shared lockfile, and warning policy.
- No runtime dependency, API, schema, persistence, deployment-topology, or product behavior changes.
