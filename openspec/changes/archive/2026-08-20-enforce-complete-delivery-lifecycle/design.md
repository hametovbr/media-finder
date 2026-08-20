## Context

See `proposal.md` for the motivation and `specs/deployment-and-delivery/spec.md` for the completion contract. The repository already has generated OpenSpec lifecycle skills, manually maintained Media Finder skills, policy tests, seven required `verification/*` pull-request checks, and protected-branch publication guidance. The gap is semantic: several handoffs use “complete” for a phase without stating that the overall work item remains open, and the archive and publication obligations are not expressed as one ordered closure chain.

Generated `openspec-*` skills are owned by the pinned OpenSpec CLI and must not be edited manually. Planning, apply, and archive remain distinct authorization boundaries. The current checkout also contains an already implemented UI reconciliation change and an earlier UI archive, so implementation of this governance change must preserve and close that work rather than replacing or hiding it.

Initial Starlette `TestClient` runs hung inside the restricted execution sandbox, but the same hang reproduced after `httpx2` was installed; it is therefore an environment limitation of the sandboxed lifespan portal, not evidence against the fallback. A controlled isolated run outside that restriction failed at collection without `httpx2` because the deprecated fallback warning is promoted to an error, while the same focused test passed with locked `httpx2`. Starlette declares `httpx2>=2.0.0` for this test-client path, while Media Finder still needs `httpx` independently for production integration transports.

## Goals / Non-Goals

**Goals:**

- Establish one unambiguous vocabulary for phase completion, overall completion, blocking evidence, and next action.
- Make OpenSpec sync/archive and protected-branch publication an ordered, mandatory closure chain.
- Put stable invariants in `AGENTS.md`, conditional execution details in project skills, and mechanically checkable structure in tests.
- Preserve exact-SHA verification and the existing seven required check contexts.
- Pressure-test every materially changed manually maintained skill with honestly classified evidence.
- Make Starlette test-client execution deterministic in both the shared repository environment and the built-in UI's isolated test environment.

**Non-Goals:**

- Modify generated OpenSpec skill bodies or replace the OpenSpec CLI.
- Add a workflow orchestrator, bot, service, status database, custom parser, or new GitHub check context.
- Collapse retrospective proposal/apply approval or the separate archive authorization into one pre-approval.
- Change runtime code, product behavior, public contracts, branch-protection configuration, or release semantics.
- Replace the production `httpx` transport or add `httpx2` to any runtime dependency set.
- Claim that repository prose can force an agent or GitHub to act when credentials, permissions, review, or required checks are unavailable.

## Decisions

### 1. Model completion as an ordered repository invariant

`AGENTS.md` will define two distinct statuses:

- **phase complete** means the currently authorized OpenSpec or verification operation met its own exit criteria;
- **overall work complete** means every applicable OpenSpec and publication gate has completed through confirmed merge into `main`.

For OpenSpec changes, the closure order is implementation and pre-archive verification, canonical spec sync, archive, deliberate commit shaping, exact-candidate local verification, branch push, pull request, required exact-head checks and review, merge, and post-merge ancestry confirmation. For legitimate OpenSpec bypasses, the first three gates are explicitly not applicable, not silently omitted.

This is preferable to using “done” contextually because every handoff can state the same three facts: completed phase, overall status, and next required action or authorization.

### 2. Preserve authorization boundaries while making continuation mandatory

Proposal, update, and apply remain terminal for their user turn. Apply handoff must therefore say “implementation phase complete; overall work incomplete” and request the next authorized verification/archive phase. Archive remains separately authorized and must select synchronization whenever applicable; choosing archive without required sync cannot satisfy the repository completion contract.

After a successful separately authorized archive, the already requested ordinary delivery chain—commit shaping, push, pull request, checks, review, and merge—continues under the publication skill unless the user explicitly narrows or stops it, or an external gate blocks progress. This preserves the high-value retrospective planning and archive gates while eliminating an extra handoff at which already mandated publication could be forgotten.

Alternatives rejected:

- **One up-front authorization for every phase:** conflicts with retrospective approval and makes an unseen proposal effectively pre-approved.
- **Require a new user message after every mechanical publication step:** adds no design decision or safety value once the archived candidate and intended delivery are approved, and creates more omission points.
- **Edit generated lifecycle skills:** creates drift from the pinned CLI and violates existing ownership.

### 3. Use existing owners instead of adding an orchestration layer

Stable applicability and completion invariants belong in `AGENTS.md`. `developing-media-finder-changes` owns the apply handoff language. `verifying-and-publishing-media-finder` owns pre-archive readiness, post-archive candidate shaping, exact-SHA checks, PR merge, and final handoff. `reviewing-media-finder-changes` needs only enough alignment to prevent a “merge yes” verdict from being presented as overall completion. The skill-maintenance procedure itself remains the owner of evaluation method and does not need a new parallel workflow.

The generated archive skill continues to perform intelligent inline sync. Project policy constrains the acceptable selection and completion claim; it does not duplicate archive mechanics.

No new runtime component is justified: the change is repository guidance plus tests and evidence documentation.

### 4. Test stable structural obligations, evaluate conditional judgment behavior

`tests/test_project_skills.py` will assert stable cross-file facts such as:

- overall completion is explicitly tied to sync/archive and confirmed merge;
- apply handoff distinguishes phase completion from overall completion;
- publication guidance requires logical commit shaping, a non-`main` PR branch, exact-head checks, merge, and post-merge confirmation;
- generated OpenSpec skills remain outside the manually maintained edit surface.

Tests will not attempt to parse prose control flow or prove actual agent behavior. For each materially changed manual skill, documentation will record a realistic no-target-skill control or historical observed failure and a same-prompt post-skill forward test, including inherited instruction sources and causal limitations. Skill cycles will run serially so each result is attributable to a stable file revision.

### 5. Shape and verify the final candidate after OpenSpec closure

The delivery commit must contain the synchronized canonical spec and archived change, so final commit shaping happens after archive. One cohesive commit is preferred; multiple commits are allowed only for genuinely separate logical areas and must each leave reviewable history. Incidental work-in-progress commits are squashed before the first publication of the final candidate.

Required local gates are run against the shaped candidate, followed by a cleanliness and HEAD recheck. The pushed PR head SHA is then bound to all required checks and review. Merge is allowed only for that head. Overall completion requires evidence that the merged result is reachable from `main`; a green workflow for another SHA is insufficient.

### 6. Use Starlette's declared test transport instead of its deprecated fallback

Add `httpx2>=2,<3` to the root development dependency group and the built-in UI's isolated test dependency group, then regenerate the shared uv lockfile. Keep the existing `httpx` dependencies because production modules and their transport tests use that API independently of Starlette's test client. Remove the two targeted Starlette deprecation-warning exemptions once `httpx2` is locked so warnings return to the repository-wide error policy.

This is the lowest sufficient configuration-level correction: it follows Starlette's declared optional dependency and adds no adapter, compatibility shim, package boundary, runtime owner, or service. Pinning the supported major range keeps resolution reproducible without duplicating the exact transitive patch version already captured by `uv.lock`.

Alternatives rejected:

- **Keep the deprecated fallback and warning ignores:** the fallback can execute when its warning is suppressed, but retaining it requires a permanent exception to the repository-wide warnings-as-errors policy and ignores Starlette's declared replacement path.
- **Patch or wrap Starlette `TestClient`:** creates repository-owned compatibility code for behavior already supplied by Starlette's declared test dependency.
- **Replace production `httpx` with `httpx2`:** expands runtime scope and would require a separate compatibility review with no evidence that it is needed for this change.

## Risks / Trade-offs

- **[Risk] Separate authorization boundaries still require another user turn after apply.** → Every terminal handoff names the next required authorization and keeps overall status incomplete; the boundary is intentional rather than accidental abandonment.
- **[Risk] GitHub credentials, review, branch protection, or checks may block merge.** → Keep the task blocked or incomplete, preserve the PR and exact evidence, and never substitute a local pass or stale workflow.
- **[Risk] Literal policy assertions become brittle or encourage keyword compliance.** → Limit tests to stable routing/completion invariants and retain pressure scenarios for judgment-heavy behavior.
- **[Risk] Editing several manual skills makes causal evaluation noisy.** → Change and evaluate one manual skill at a time, record inherited context, and avoid claiming isolation where none exists.
- **[Risk] Existing dirty UI work could be mixed or lost.** → Preserve it, create a feature branch before publication, close each active OpenSpec change in order, and use logical commit boundaries if the UI and governance changes remain independently reviewable.
- **[Risk] `httpx2` is a separately evolving test-only package.** → Constrain it to Starlette's supported major line, lock the resolved version, exercise focused and full TestClient suites, and let dependency updates surface incompatibility under warnings-as-errors.
- **[Risk] A restricted runner can make a working TestClient path look hung.** → Reproduce the same locked candidate in an execution boundary that permits the lifespan portal, classify the restricted run as blocked rather than failed, and use controlled no-dependency versus locked-dependency runs for causal claims.

## Migration Plan

1. Capture and document baseline behavior for the handoff and publication pressure scenarios.
2. Update the stable completion invariant and policy tests.
3. Update and forward-test each affected manual skill serially.
4. Validate repository guidance and all proportional repository gates.
5. Add and lock `httpx2` in both test dependency scopes, remove the fallback warning exemptions, and rerun the focused reproducer followed by the full Python suite.
6. Complete the already active UI reconciliation sync/archive, then sync and archive this governance change under their separately authorized archive phases.
7. Shape the final logical commit set on a non-`main` branch, rerun exact-candidate gates, push, open the pull request, verify the exact head, merge, and confirm `main` ancestry.

Rollback is a normal revert through a new reviewed pull request. No runtime or data migration exists.
