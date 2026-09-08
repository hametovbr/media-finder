# Incremental implementation evidence

## Hosted checkpoint and browser correction — 2026-09-08

The preliminary publication blocker below is historical and resolved. Draft PR [31](https://github.com/hametovbr/media-finder/pull/31) tests head `ae7d78b455b372c7154d7066960bc7611ca02fb3`, base `3e47f352f0830b0bd5fd9f00f6a52a35b5d2ab47`. Its tree `db2a37d0e0d0852fd36ff8b6cbfb6a4344afe91e` exactly matches local checkpoint `6858005c1436caa29cd1cb82a4ae58c8f2b8e83d`; commit metadata differs. The change remains active, tasks 5.1–5.4 pending; no merge or archive acceptance.

- Run [34279131084](https://github.com/hametovbr/media-finder/actions/runs/34279131084), attempt 1: six required non-browser jobs passed. Browser job `102239375035` ran the pinned browser successfully: **75 passed / 11 failed**, exit 1. This is valid hosted RED, not a local environment failure.
- Failures: five CSV cases selected both the file button and textarea; four secondary-field cases selected common and episode fields; two mobile dirty-navigation cases targeted hidden desktop navigation. Repair is bounded to exact/scoped E2E locators and the real mobile menu, without changing product behavior or weakening assertions.
- Artifact `10076981978`, SHA256 `5bd6391f961ceaf98b6af1eeaa81d889ffc3b77efe03e388e806be426e12dafc`, was downloaded completely and verified. Provenance: checkout/event `9ca21d59a795b6261580928047121820ef2a48e6`, the head/base above, Node `v24.20.0`, Playwright `1.62.1`, Chrome for Testing `151.0.7922.34`. This is synthetic-merge evidence for that head/base pair.
- Only 10 of 20 Manual captures exist. The report's empty `missingCaptures` array applies to the preserved recovery matrix, not Manual acceptance. Primary inspection of destructive RU/360, alternate RU/360 and dirty RU/1280 also found partially transparent dialogs captured during entry transitions. Add an observable settled-opacity wait before capture; do not change production animation or introduce fixed sleeps. Missing/unstable captures block task 5.2.
- Correction unit `manual_e2e_repair`: Luna Max, shared clean baseline above, sole implementation ownership of `packages/builtin-ui/web/e2e/shell.spec.ts`; primary owns evidence and verification. A fresh hosted run and screenshot inspection are required after repair. Test discovery is not runtime GREEN.
- Repair source SHA256 `40a96d41b68619e88fd2de0938d04605fc45051d7048339e53b0e5968574ed4c`: primary inspected the diff and reran targeted Prettier/Oxlint, UI TypeScript, and pinned Playwright discovery (86 tests: 50 shell including 20 Manual captures, 36 recovery), all exit 0. Full `pnpm ui:test`: 14 files / 162 passed; `pnpm ui:a11y`: 17 passed / 145 filtered skips. Contract check and production build passed with unchanged packaged assets (`index-CYtf72WC.js`). No tests removed/skipped, assertion relaxation, fixed sleeps, production animation or workflow changes. Hosted runtime GREEN remains outstanding.
- Independent Terra review of that exact source hash: Critical 0 / Important 0 / Minor 0; GO for hosted rerun only, not merge. Primary full UI format/lint/type, documentation (454 files), strict OpenSpec (10/10) and diff checks passed. Only E2E and this evidence ledger differ from the preliminary checkpoint.

## Historical preliminary publication blocker

Local implementation and pre-checkpoint review passed. Automatic approval review rejected uploading the design blob to `hametovbr/media-finder`, classifying the full internal design as sensitive egress without sufficiently specific payload/destination authorization. The rejected action was not retried through another mechanism. Only the small `.openspec.yaml` blob was uploaded before the rejection; no remote branch, commit or PR was created. Browser execution and screenshot inspection remain blocked pending publication. Preserve the complete local checkpoint; do not omit planning artifacts to evade the rejection.

## Local implementation acceptance — 2026-09-08

Tasks 1–4 are implemented and accepted (11/15). The remaining 5.x items require candidate-bound hosted browser evidence, final gates and review. This remains an active, uncommitted change above `3e47f352f0830b0bd5fd9f00f6a52a35b5d2ab47`; no archive or final delivery claim.

- Primary full UI command from `packages/builtin-ui`: `pnpm exec vitest run --config web/vite.config.ts --passWithNoTests`, 14 files / 162 tests, exit 0 (14:19 UTC). This closes task 4.3's full-suite requirement after its condition-based visibility fix.
- Added primary proof for oversized JSON file rejection before reading and pasted-byte bounds; keyboard safe action and focus return for add/edit alternate, reset and navigation dialogs. The first reset assertion incorrectly expected an empty initial tags list; corrected to the actual rich fixture, preserving the intended test.
- Controlled router navigation in the alternate-review test now runs inside React `act`, so the attempted navigation/reset is processed before keyboard cancellation. Prior failure came from observing an unflushed imperative router update. Disabled underlying controls and repeated form submission remain asserted; no product navigation fallback was introduced.
- Terra fixed test fixture refetch after duplicate confirmation by retaining the confirmed item; a successful confirmation no longer permits a mock null response to overwrite detail cache.
- Primary discovered Mantine label nowrap and fixed it through local label styles. A focused height regression subsequently failed (missing `height: auto`); both page action styles now allow height growth and retain a 2.25rem minimum. Focused GREEN: 1 passed / 26 skipped. After that narrow style correction, primary root-script gates passed: `pnpm ui:build`, `pnpm ui:format`, `pnpm ui:lint`, `pnpm ui:type`, `pnpm ui:a11y` (17 passed / 145 skipped), and `pnpm ui:test` (14 files / 162 tests, 14:21 UTC). Build invokes `pnpm ui:contract`; generated JavaScript is `index-CYtf72WC.js`. `pnpm docs:check` (454 files), `pnpm spec:validate` (10/10) and `git diff --check` also passed. The final source/test bytes are frozen for preliminary hosted verification.
- Final independent Terra review refreshed after the height correction and primary tests: pre-checkpoint GO, no source or focused-coverage findings; hosted browser/CI and final delivery review remain pending. Earlier independent Terra review before that final height-only correction: Critical 0 / Important 0 / Minor 0, source and focused-coverage GO conditional on final gates and browser acceptance. No API/backend/dependency/workflow/general-rule changes. Final-head review still required.
- Luna final E2E discovery: 50 shell tests, including managed browser forward navigation; the preserved recovery matrix plus 20 new Manual captures are authored. Discovery is not execution. Pinned local Chromium remains unavailable; use the authorized preliminary draft PR for hosted evidence.

## Integrated implementation checkpoint — 2026-09-08

Current phase: apply; accepted task checkboxes remain 1.1, 1.2, 3.1 and 4.1 (4/15). Implementation is uncommitted above main `3e47f352f0830b0bd5fd9f00f6a52a35b5d2ab47`; active artifacts remain required. No archive, PR, merge or edge claim.

- Task 4.1 primary acceptance: editor plus i18n suites 19/19 and TypeScript passed after disclosure/count implementation. A later catalog-reference-only correction in editor tests also passed those 19 tests.
- Recovered integrated Manual/i18n candidate: 5 files / 60 tests passed with TypeScript (13:54 UTC), before alternate-consent additions.
- Terra alternate-consent implementation: add/edit suites 37/37 and TypeScript passed. Independent review identified incomplete scenario proof; these tasks are not accepted yet.
- Primary full `pnpm ui:test` (14:05 UTC): 152 passed / 1 failed. The item A-to-B setup exceeded the 5-second test deadline; long character-by-character CSV setup is being replaced with direct bulk input while retaining navigation assertions. No blanket timeout or production animation change.
- Primary `pnpm ui:a11y`: 17 passed / 136 skipped, exit 0. This is the accessibility-filtered suite, not full UI acceptance.
- Primary lint and contract checks passed. Documentation check rejected Cyrillic literals in new tests; tests are being changed to consume the existing catalogs/user-metadata fixtures without changing policy.
- Luna authored the five-state EN/RU 360x800/1280x800 screenshot matrix and scoped browser scenarios, preserving existing captures. Discovery: 83 tests. Browser execution and screenshot inspection remain unavailable locally and block acceptance; discovery is not a pass.
- Independent Terra review: no concrete production defect found in the intermediate diff; missing forward-history, pending-read invalidation and alternate-consent/failure cases are being completed. The initial claim that add-page unmount coverage was absent was retracted: the existing deferred save/JSON-unmount test covers it.

Next: finish page focus/wrapping and scenario coverage, freeze the combined candidate, rerun affected/full gates, rebuild assets, obtain independent review and current hosted browser proof. Historical entries below are evidence for earlier slices only.

## Operation and destructive-review work — in progress

Primary owns integration/locales/evidence; Terra `manual_operations` owns add/edit pages/tests; Luna Max `manual_destructive` owns editor/tests. Base remains `3e47f352f0830b0bd5fd9f00f6a52a35b5d2ab47`; all implementation is uncommitted. Spec SHA256 `aea9655dcd18504cc349c993483b12babf0dc1a3156062894586c659eb7a2a59`; design SHA256 `f41852f6b0f241cc083ec8eea68c54773756ddfff2c6fc3352d005f71b0aa8ce`.

- Task 3.1: Luna observed focused RED (4 failed / 7 passed), implemented stable destructive intents and page admission callback; primary inspected actual editor and independently ran `pnpm exec vitest run --config web/vite.config.ts web/src/manual/manual-editor.test.tsx`: 11/11, exit 0. Keyboard addition coverage retained; cancellation, exact episode/season deletion, populated kind transition, safe focus and portal guard tested. Primary focused Prettier check passed. Task accepted before subsequent disclosure work begins; rerun integrated evidence after task 4.1.
- Tasks 2.1–2.3: worker added synchronous gates, frozen request snapshots, safe read generations, no retry, busy navigation reset and destination-specific success bypass. Worker add/edit suite reached 28/28 after deferred completion, unmount, file replacement/clear/error and pending confirmation cases. Primary independent run overlapped an intermediate test adaptation for not-yet-created Additional fields: 27/28, missing button. That run is not final candidate acceptance; rerun after disclosure and page tests agree.
- Task 4.3: opacity-0 immediate assertion reproduced again in the expanded page suite, then replaced with condition-based visibility wait. Worker page suite passed afterward; production animation untouched. Full UI suite remains required before checking this task complete.
- Primary operation-localization RED: `pnpm exec vitest run --config web/vite.config.ts web/src/i18n.test.ts`: 1 failed / 5 passed, missing pending key. GREEN after EN/RU additions: 6/6. Later destructive/disclosure/navigation copy needs final integrated locale checks.

Task 3.2 dirty guards and 4.1 secondary disclosure are now active, with disjoint page/editor ownership. No new general repository rules, skills, backend/DTO/dependency/workflow changes or publication. No overall acceptance is claimed.

## Lossless draft slice — 2026-09-08

Base HEAD: `3e47f352f0830b0bd5fd9f00f6a52a35b5d2ab47` on `plan/ui-manual-editor-safety`. Evidence covers the uncommitted tasks 1.1–1.2 diff, not a delivered candidate. Terra implemented; the primary independently inspected the diff and reran the four Manual suites.

- Terra RED: from `packages/builtin-ui`, `pnpm exec vitest run --config web/vite.config.ts web/src/manual/manual-document.test.ts web/src/manual/manual-editor.test.tsx web/src/manual/manual-add-page.test.tsx`: 3 failed / 15 passed. Missing projection and visible `DramaComedy` instead of `Drama, Comedy, ` were observed before implementation.
- Terra GREEN: same command, 3 files / 20 tests passed. Focused Prettier and TypeScript checks passed.
- Primary GREEN: same command plus `web/src/manual/manual-edit-page.test.tsx`: 4 files / 27 tests passed, exit 0. `pnpm exec tsc -p web/tsconfig.json --noEmit` passed.
- Review corrections: raw values use string types; fieldwise raw equality ignores object insertion order; four-field initialization avoids an unsafe assertion.

Raw text is page-owned and controlled; changed-field-only request projection preserves untouched comma-bearing arrays and rich metadata. Comparison strips row keys and includes collection selection; navigation wiring belongs to task 3.2. No API, backend, dependencies, general repository rules or skills changed.

Tasks 2–5 remain incomplete. The known task 4.3 assertion was not changed. No full UI, new browser acceptance, generated build, archive, PR or delivery is claimed. The pinned Chromium executable is absent locally; required browser evidence must use the approved hosted verification path unless the local environment becomes available.
