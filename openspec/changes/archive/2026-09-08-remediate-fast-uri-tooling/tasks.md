## 1. Candidate and affected baseline

- [x] 1.1 Confirm approval including skip_specs, isolate from current main while preserving planning artifacts, and record candidate SHA, clean baseline, pinned tools, and permitted execution boundaries.
- [x] 1.2 Capture RED evidence: resolve fast-uri through Ajv's actual module context and compare installed and locked versions against current upstream affected ranges. Confirm 3.1.7 is available and remains outside those ranges; otherwise stop for revised planning. Record safe sources and dates, not exploit payloads.

## 2. Minimal remediation

- [x] 2.0 Confirm approval of the revised scoped-override design; refresh main/candidate identity and advisory/registry evidence before resuming. Preserve tasks 1.1 and 1.2 as historical baseline evidence, not approval of the revision.
- [x] 2.1 Add only the root workspace override `ajv@8.17.1>fast-uri: 3.1.7` and use pinned pnpm to regenerate the lockfile. Inspect the complete diff; stop for broader overrides, direct dependencies, Ajv changes, release-age/trust-policy exclusions, unrelated packages, or product changes.
- [x] 2.2 Perform a fresh frozen-lockfile installation in an isolated verification environment. Confirm the actual Ajv resolver uses 3.1.7 and no affected fast-uri entry remains in the resolved graph; record current advisory or dependency-scanner evidence and any unavailable checks.

## 3. Regression verification and handoff

- [x] 3.1 Run pnpm module-conformance:test and pnpm module-conformance:validate; retain results for the candidate without altering validators or fixtures to accommodate failures.
- [x] 3.2 Run pnpm spec:validate, pnpm docs:check, pnpm delivery:validate, UI format/lint/type/unit/contract/build gates, and confirm generated contracts and static assets are unchanged. Record blocked host-dependent gates explicitly; do not reuse pre-update dependency evidence.
- [x] 3.3 Obtain independent review of the exact parent-version override scope, corresponding lockfile diff, future reassessment/removal conditions, source-backed advisory coverage, compatibility results, and the applicability of SECURITY.md's live-check condition. Confirm there are no security-policy, scanner, security-exception, module-ownership, or secret-boundary changes; retain the separate Ajv and smol-toml findings as unresolved.
- [x] 3.4 Record safe verification evidence and finding disposition with exact candidate identity; report apply completion separately from overall delivery. Identify any separately authorized hosted verification and archive as next gates. Keep canonical specs unchanged because deltas are intentionally skipped; final PR checks, merge, and normal edge verification remain required after closure, not actions authorized by this task list.
