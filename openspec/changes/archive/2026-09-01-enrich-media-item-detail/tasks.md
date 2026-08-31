## 1. Establish focused RED coverage

- [x] 1.1 Enrich the deterministic media-detail fixtures and add focused component assertions for first case-insensitive poster selection, exact unchanged `src`, lazy/no-referrer attributes, informative localized naming, visible original title/year, and trimmed ordered genres; run the focused media-detail test and record the expected RED result.
- [x] 1.2 Add focused component cases for absent and whitespace-only optional values, missing and failed poster fallback, failure state resetting for a changed poster URL, preserved `Find release` and Manual-only edit behavior, and unchanged loading/404/410 presentation; run them and record the expected RED result before production edits.
- [x] 1.3 Add English/Russian detail accessibility coverage and Playwright expectations for exact poster/fallback names, deterministic image abort, rich provider and Manual detail, action availability, and no horizontal document overflow at the supported mobile viewport; run the applicable focused checks, including host Playwright, to establish RED where current behavior is missing.

## 2. Implement the rich detail presentation

- [x] 2.1 Update `MediaDetailPage` to derive trimmed optional text, filtered ordered genres, and the first case-insensitive poster from the existing generated `MediaItemDetail`, with URL-scoped image failure and no backend, SDK, provider, or URL transformation logic.
- [x] 2.2 Add the page-local responsive poster/content styling and English/Russian detail labels, reusing the existing generic localized poster names and local MF fallback while preserving the current title, type, provider, plot, actions, hierarchy/history omissions, and safe error states.
- [x] 2.3 Run the focused component, accessibility, and host browser cases to GREEN; confirm the exact direct untrusted URL behavior, local fallback isolation, keyboard-accessible actions, and mobile no-overflow contract.

## 3. Verify the exact candidate

- [x] 3.1 Format the touched UI sources, then run `pnpm ui:format`, `pnpm ui:lint`, `pnpm ui:type`, `pnpm ui:contract`, `pnpm ui:test`, `pnpm ui:a11y`, and `pnpm ui:build`; review the regenerated tracked static assets and confirm that the generated control client remains unchanged.
- [x] 3.2 Run host `pnpm ui:browser` and host `uv run python packages/builtin-ui/tests/run_isolated.py unit` so Chromium, local-server, independent-wheel-build, and packaged-static behavior are verified at their supported execution boundary.
- [x] 3.3 Run `pnpm py:format`, `pnpm py:lint`, `pnpm py:type`, host `pnpm py:test`, and `pnpm docs:check` to prove that the presentation-only change preserves repository quality and package boundaries.
- [x] 3.4 Run `pnpm spec:validate` and `openspec status --change enrich-media-item-detail`; confirm every approved scenario is covered, every implementation task is complete, the worktree contains only reviewed change paths, and no higher architecture rung, compatibility mechanism, migration, or unapproved behavior entered the candidate.
