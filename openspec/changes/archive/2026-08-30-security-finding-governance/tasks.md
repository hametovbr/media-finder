## 1. Deterministic exception contract

- [x] 1.1 Add focused delivery-validator tests for the empty version-1 manifest and for rejected unknown versions, missing fields, invalid enums, duplicate IDs, unsafe paths, missing native targets, absent exception-ID markers, invalid date order, review windows over 90 days, and expired exceptions; run them and record the expected RED result before implementation.
- [x] 1.2 Add `.github/security-exceptions.yaml` with an empty version-1 exception list and implement manifest parsing and validation in the existing delivery validator with an injectable UTC current date.
- [x] 1.3 Add positive fixtures for active repository-file and GitHub-hosted exception locators and run the focused delivery-validator suite to GREEN.

## 2. Authoritative GitHub verification

- [x] 2.1 Add focused tests for enabled, disabled, unauthorized, unavailable, and malformed repository-security responses plus active and mismatched GitHub-hosted dismissals; assert that failures expose only safe repository state and exception identifiers, then run them to the expected RED result.
- [x] 2.2 Implement the narrow `pnpm security:verify -- --repository OWNER/REPO` adapter using argument-array GitHub CLI execution, exact repository binding, minimum response fields, hosted-dismissal reconciliation, secret-safe output, and non-zero blocked or failed exits.
- [x] 2.3 Run the live read-only command against `hametovbr/media-finder`; confirm secret scanning and push protection are enabled and record no token, alert body, location, raw payload, or sensitive URL in the change evidence.

## 3. Policy and contributor workflow

- [x] 3.1 Expand `SECURITY.md` with the three-state finding lifecycle, ownership and safe tracking rules, native suppression and manifest procedure, 90-day UTC expiry and renewal/removal rules, secret rotation/revocation requirements, push-protection bypass handling, and the authoritative verification command.
- [x] 3.2 Update `CONTRIBUTING.md` with the security-affecting-change verification gate and clarify that unavailable GitHub evidence blocks delivery without adding the live check to ordinary required pull-request jobs.
- [x] 3.3 Verify that all new public repository metadata, fixtures, test diagnostics, and documentation remain English-only and contain no credentials, authenticated URLs, raw findings, exploit material, or private service details.

## 4. Regression and scope verification

- [x] 4.1 Run `pnpm delivery:test`, `pnpm delivery:validate`, `pnpm security:verify -- --repository hametovbr/media-finder`, `pnpm docs:check`, and `pnpm spec:validate`; record each exit status and treat unavailable live evidence as blocked rather than passed.
- [x] 4.2 Run `pnpm ui:format`, `pnpm ui:lint`, `pnpm ui:type`, `pnpm ui:test`, `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, and `uv run pytest` to confirm the governance tooling does not regress existing repository gates.
- [x] 4.3 Run `pnpm assets:build`, verify `git diff --exit-code -- packages/builtin-ui/src/media_finder_builtin_ui/static`, and run `git diff --check` to confirm production assets and patch hygiene remain unchanged.
- [x] 4.4 Perform the final subtraction and security review: confirm no scanner installation, GitHub setting mutation, new required check context, runtime dependency, process, service, database, API, module, UI, authentication, network-exposure, or About/Credits change entered the implementation.
- [x] 4.5 Run `openspec validate security-finding-governance --strict` and `openspec validate --all --strict`, confirm every task has evidence, and leave canonical synchronization, archive, commit, push, pull request, checks, and merge for their separately authorized phases.

## 5. Review hardening

- [x] 5.1 Add focused RED validator tests for short and prefix-colliding exception markers, a repository-file symlink that resolves to the manifest, a future approval date, malformed YAML containing a sentinel source line, and an invalid identifier containing a sentinel value; confirm diagnostics do not reproduce unvalidated input.
- [x] 5.2 Implement exact namespaced marker binding, resolved-path containment and manifest self-reference rejection, future approval rejection, and static validation diagnostics; run the focused delivery-validator tests to GREEN.
- [x] 5.3 Add focused RED live-adapter tests for the complete `gh api --hostname github.com` argument array, an environment-selected alternate host, null and array JSON payloads, short and prefix-colliding hosted-dismissal markers, and subprocess timeout classification.
- [x] 5.4 Implement explicit `github.com` selection, the 30-second subprocess timeout, safe hosted-response shape validation, and exact namespaced hosted marker binding; run the focused security-verifier tests to GREEN.
- [x] 5.5 Update `SECURITY.md` with the exact marker contract, resolved-target restriction, non-future approval rule, and blocked timeout behavior; repeat focused tests, `pnpm delivery:validate`, `pnpm security:verify -- --repository hametovbr/media-finder`, `pnpm docs:check`, `pnpm spec:validate`, and all repository format, lint, type, test, asset-build, and patch-hygiene gates required by the current project stage.
- [x] 5.6 Repeat the final subtraction and secret-safety review, obtain an independent review of the exact candidate, run strict change and all-spec validation, and leave canonical synchronization, archive, amend, push, pull request, exact-head checks/review, and merge for their authorized phases.
