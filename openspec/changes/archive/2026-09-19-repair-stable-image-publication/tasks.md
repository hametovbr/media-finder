## 1. Tests first

- [x] 1.1 Add failing delivery-policy tests for the manual entry point: it is accepted only with a main-only guard, a single tag input and a release-resolution step whose failure skips publication, and it is rejected when any of those is missing or when the entry point is not main-only. Observed RED: with the assertions in place and the previous workflow, `node scripts/validate-delivery.mjs` reported twelve failures, including `stable publishing must use published releases and one manual entry point`, `manual publication must be main-only` and `manual publication must resolve and validate the requested stable release before any registry access`.
- [x] 1.2 Add failing assertions that the accepted shape keeps the seven verification contexts, the permission separation, the published-releases-only rule for the event path, the single concurrency group without cancellation, and the unchanged publisher command and immutable-state guard. Five mutation tests were added: an extra manual input, a non-main-only condition, a removed resolution step, a publisher taken from the release checkout, and an unpinned release identity — each rejected with its own message.
- [x] 1.3 Observe the current validator reject the manual entry point, so the guards are proven to be enforced rather than assumed. Recorded above: the previously delivered workflow fails the new assertions, and the delivered workflow passes them.

## 2. Implement the minimum change

- [x] 2.1 Add the `workflow_dispatch` trigger with one `release_tag` input to `.github/workflows/release.yaml`, guarded to `refs/heads/main`, leaving the existing release trigger and concurrency group unchanged.
- [x] 2.2 Add a release-resolution step that requires the named tag to resolve to an existing published, non-prerelease, non-draft release whose commit's `VERSION` equals the tag and whose release commit carries all seven successful `verification/*` contexts, and that exports the resolved commit; the publication job runs only when it succeeds.
- [x] 2.3 Check out the resolved release commit as the workspace and run the publisher fetched from the dispatch revision from a runner temporary path, overriding the step's event revision with the resolved release commit so the publisher's identity check compares like-for-like. The trusted checkout is removed from the workspace before publication, so the tree stays the release commit.
- [x] 2.4 Extend `scripts/validate-delivery.mjs` with the assertions from 1.1 and 1.2, allow packages write on the gated manual job, and replace the superseded single-trigger assertion.
- [x] 2.5 Update `docs/release-automation.md` so the documented recovery path matches what the workflow now does, including that a repair never moves a tag or rebuilds an existing immutable image.

## 3. Verify

- [x] 3.1 `node --test scripts/validate-delivery.test.mjs`: 138 passed; `node --test scripts/release-publication.test.mjs`: 35 passed; `node --test scripts/release-automation.test.mjs`: 113 passed. The new guards fail on the superseded workflow shape and pass on the delivered one.
- [x] 3.2 Repository gates on this candidate, all passing: `pnpm delivery:test` 160 passed; `pnpm delivery:validate`; `pnpm docs:check` 492 files; strict `pnpm spec:validate` 10 passed, 0 failed; `uv run ruff format --check .` 334 files; `uv run ruff check .` clean.
- [x] 3.3 Complete and coherent: the controller, the publisher and the application are unchanged, the entry point adds no behaviour beyond the guarded repair path, and the already published `v0.5.0` tag, target commit and release object are untouched.
