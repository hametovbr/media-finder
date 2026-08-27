## 1. Delivery-policy TDD

- [x] 1.1 Add one focused mutation test for each of `pnpm ui:format`, `pnpm ui:lint`, and `pnpm ui:test`; build an otherwise compliant workflow fixture, substitute the selected command with a non-equivalent command, and record the expected RED result showing that the current validator does not reject the mutation.
- [x] 1.2 Extend the structured verification validator to require execution of all three exact commands in the existing `python` job by reusing its shell-command helper; run the focused mutation tests to GREEN while preserving the expected failure of the current-workflow structural test until the workflow is updated.

## 2. Reusable Verification

- [x] 2.1 Add separately named `pnpm ui:format`, `pnpm ui:lint`, and `pnpm ui:test` steps after locked asset-tool installation and before frontend production build in the existing `python` job; do not add or rename jobs, permissions, setup actions, dependencies, or root scripts.
- [x] 2.2 Run `pnpm delivery:test` and `pnpm delivery:validate` to GREEN and confirm the validator still enforces exactly the seven protected job identifiers.

## 3. Exact-Candidate Verification

- [x] 3.1 Run `pnpm ui:format`, `pnpm ui:lint`, `pnpm ui:type`, `pnpm ui:test`, `pnpm ui:a11y`, and `pnpm ui:build`, then confirm rebuilding the built-in UI leaves its checked-in static assets unchanged.
- [x] 3.2 Run `pnpm docs:check`, `pnpm spec:validate`, `pnpm module-conformance:test`, and `pnpm module-conformance:validate`.
- [x] 3.3 Run `pnpm py:format`, `pnpm py:lint`, `pnpm py:type`, and `pnpm py:test` with the repository's pinned toolchain and cache settings.
- [x] 3.4 Run `pnpm ui:browser`, build the production image, and run `bash scripts/smoke-container.sh`; verify fixed smoke-test resources are absent before the run and cleaned afterward.
- [x] 3.5 Review the exact candidate for workflow permissions, immutable action pins, the unchanged seven-context set, clean diff checks, and a clean worktree before publication.
