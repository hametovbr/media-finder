# Verification record

Date: 2026-09-08. Status: revised implementation verified locally; overall delivery incomplete.

## Revised scoped-override implementation

The user approved the revised design after it was presented. Earlier failed attempts below are historical, not the current implementation result.

- HEAD and refreshed origin/main: a34b81ca98720925c497e2406fa4335d04bd0d93; branch security/remediate-fast-uri-tooling, with the two-file uncommitted implementation diff and active planning artifacts.
- Added only `ajv@8.17.1>fast-uri: 3.1.7` under workspace overrides. `pnpm install --lockfile-only --no-frozen-lockfile` exited 0 and regenerated only the corresponding lockfile entries. No other package version or security setting changed.
- Candidate lockfile SHA256: 05ec4246064f2267d98f853a8da4c7c9a669d019e0ee96bd52b5659e1be23f37. Workspace configuration SHA256: ea996adfbcdf2cc9fdb1f378fbfe7c36baa3d1a1a89977d602ecf554f6319d31.
- Fresh verification directory was populated from `git archive HEAD` with precisely those two candidate files overlaid. `pnpm install --frozen-lockfile` exited 0; actual Ajv 8.17.1 resolver returned fast-uri 3.1.7 (GREEN). Candidate and verification lockfiles/configuration compare equal. No affected fast-uri entry remains in the lockfile.
- Refreshed upstream patch advisories and registry version confirmation. Unfiltered `pnpm audit --json` exited 1 with exactly two moderate findings (Ajv and smol-toml listed below), zero high/critical, and no fast-uri advisory. This is targeted remediation evidence, not a fully clean dependency audit or proof of deployed-image security.
- Fresh-environment gates: module-conformance tests 64/64; conformance validator, delivery validator, UI format/lint/type, contract check, and production build all exited 0; UI unit tests 118/118. Built static assets compare byte-for-byte equal with the original candidate. Vite's existing large-chunk warning remains advisory and unchanged.
- OpenSpec strict: 10 passed, 0 failed; documentation: 448 files; diff whitespace check passed.
- Independent Terra review: Critical 0, Important 0; scoped implementation approved. SECURITY.md's policy/scanner/gate/exception/release-security live-check condition is not triggered by this dependency-resolution-only diff. The authenticated live check was not run, not claimed passed.
- No browser/full Python/image CI was launched in this apply turn. Archive, exact-head PR checks/review, merge, and main/edge verification remain outstanding. The repository/main finding is not closed until delivery; local candidate remediation does not imply GitHub alert closure.

User approved the presented change and autonomous continuation. Work is limited to this dependency remediation; expansion and permission failures remain stop conditions.

## Baseline

- Fetched origin/main: a34b81ca98720925c497e2406fa4335d04bd0d93.
- Isolated task branch: security/remediate-fast-uri-tooling, based on that main. Existing planning files preserved; no unrelated tracked edits.
- Node 24.19.0; pnpm 11.19.0. Ordinary available execution only; no permission escalation or credential extraction.
- Actual resolver through Ajv: Ajv 8.17.1 -> fast-uri 3.1.5. Assertion requiring 3.1.7 exited 1 (expected RED).
- `pnpm view fast-uri@3.1.7 version`: exit 0, registry returned 3.1.7. An initial invocation with unsupported fetch flags was rejected before lookup; corrected by using the supported plain command.
- Upstream advisory listing rechecked on the date above. September 2 advisories GHSA-qw65-cvwx-89v3 and GHSA-58mr-gqgx-xq4g identify 3.1.7 as the patched 3.x version; no full dependency audit is implied.
- Baseline `pnpm module-conformance:test`: 64 passed, 0 failed; `pnpm module-conformance:validate`: exit 0.

## Historical failed attempts before the design revision

The second supported mechanism, `pnpm audit --fix=update --interactive --lockfile-only --no-save`, was run with only the three fast-uri rows selected (four high advisories). Ajv and smol-toml were explicitly not selected. It exited 1: zero vulnerabilities fixed, four remained. It did not change the lockfile, but added a release-age exclusion for fast-uri@3.1.6 to pnpm-workspace.yaml. That generated, out-of-scope exclusion was immediately removed; no policy exception is retained. The approved lockfile-only mechanism has not succeeded. Stop for revised planning rather than silently introduce an override or upgrade a parent dependency.

The audit also reported two separate unresolved moderate findings: Ajv GHSA-2g4f-4pwh-qvx6 and smol-toml GHSA-v3rj-xjv7-4jmq. Owner: primary agent. Safe tracking references: https://github.com/advisories/GHSA-2g4f-4pwh-qvx6 and https://github.com/advisories/GHSA-v3rj-xjv7-4jmq. No applicability assessment, remediation, dismissal, or suppression was performed for those additional findings. They remain outside this approved change.

The supported CLI invocation `pnpm update fast-uri@3.1.7 --lockfile-only --no-save --depth Infinity` exited 0 with `Already up to date`, but did not remediate the dependency. `git diff --exit-code -- pnpm-lock.yaml package.json pnpm-workspace.yaml` exited 0; fast-uri remains 3.1.5. Lockfile SHA256: 1fa75e9613e45a9e0c0c0eed794def209762d59ba3569324659cc7a5565bcace. The package manager's supply-chain-policy check passed, which is not evidence of advisory remediation. No dependency update task is complete.

Lockfile update, fresh frozen install, resolver GREEN, regression gates, independent review, closure, and final protected-branch delivery are outstanding. No runtime exploit or image-security claim is made.
