## 1. Completion Contract

- [x] 1.1 Add focused project-skill policy tests for phase-versus-overall completion, mandatory applicable sync/archive, logical commit shaping, non-`main` pull-request delivery, exact-head checks, merge, and post-merge confirmation; run them and record the expected RED failures.
- [x] 1.2 Update `AGENTS.md` with the ordered completion contract, explicit not-applicable handling for legitimate OpenSpec bypasses, preserved retrospective phase authorization, and mandatory incomplete/blocked handoff language; run the focused tests to GREEN.

## 2. Implementation Handoff Skill Cycle

- [x] 2.1 Run and document a realistically classified no-target-skill control or historical observed failure for an apply-complete-but-unarchived handoff, including inherited instruction sources and causal limits.
- [x] 2.2 Update `developing-media-finder-changes` so its terminal apply handoff distinguishes implementation-phase completion from overall work completion and identifies the next required authorization without performing sync or archive.
- [x] 2.3 Repeat the same pressure scenario with `developing-media-finder-changes` explicitly applied, document the observable forward result, and run focused policy tests to GREEN.

## 3. Review Verdict Skill Cycle

- [x] 3.1 Run and document a realistically classified no-target-skill control or historical observed failure for a merge-ready review whose OpenSpec closure or publication state is incomplete.
- [x] 3.2 Update `reviewing-media-finder-changes` so a review verdict reports merge readiness without representing review success as overall work completion.
- [x] 3.3 Repeat the same pressure scenario with `reviewing-media-finder-changes` explicitly applied, document the observable forward result, and run focused policy tests to GREEN.

## 4. Verification and Publication Skill Cycle

- [x] 4.1 Run and document a realistically classified no-target-skill control or historical observed failure for an archived candidate with incidental commit history, pending or stale checks, or an unconfirmed merge.
- [x] 4.2 Update `verifying-and-publishing-media-finder` with mandatory pre-archive readiness, post-archive logical commit shaping, non-`main` branch push, pull-request exact-head verification/review, merge, main ancestry confirmation, and incomplete/blocked final status rules.
- [x] 4.3 Repeat the same pressure scenario with `verifying-and-publishing-media-finder` explicitly applied, document the observable forward result, and run focused policy tests to GREEN.

## 5. Repository Documentation and Verification

- [x] 5.1 Reconcile `docs/agent-skills.md` and related repository guidance with the final completion model, evaluation evidence, generated-skill ownership, and absence of a new orchestration component.
- [x] 5.2 Run `uv run pytest tests/test_project_skills.py`, strict OpenSpec validation, documentation and delivery policy checks, and verify that no generated `openspec-*` skill body changed.
- [x] 5.3 Reproduce a controlled RED outside the restricted sandbox in an isolated no-dev environment without `httpx2`, where the fallback deprecation fails under warnings-as-errors; classify the sandboxed `TestClient` hang separately as an environment limitation, add `httpx2>=2,<3` to the root development and built-in UI isolated test dependency groups, regenerate `uv.lock`, and remove both targeted fallback warning exemptions without changing runtime dependencies.
- [x] 5.4 Run the focused API `TestClient` reproducer in an execution boundary that permits the lifespan portal and run `uv run python packages/builtin-ui/tests/run_isolated.py unit` to GREEN; confirm the locked environments select `httpx2` and no longer emit or suppress the fallback deprecation.
- [x] 5.5 Run the repository format, lint, type, Python test, frontend test, browser, production build, package, and image/delivery gates required by the current project stage; record unavailable external evidence as not run or blocked.
- [x] 5.6 Re-read the proposal, delta spec, design, tasks, resulting diff, exact HEAD, and worktree state; resolve any contradiction and report the implementation phase complete while the overall work remains incomplete pending separately authorized OpenSpec closure and protected-branch delivery.
