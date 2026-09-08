## Context

See proposal.md for motivation. Investigated main is a34b81ca98720925c497e2406fa4335d04bd0d93; local d28095f3dcd4dc4727a4d8738e435b9d11f28a42 has the same tree. Root Ajv 8.17.1 permits fast-uri ^3.0.1. The identified consumer compiles a local schema in scripts/validate-module-conformance.mjs and validates repository fixtures. No direct browser import was found; the Python image does not explicitly install Node tooling. These are static observations, not exhaustive exploit or image analysis.

Dependabot attempted a recursive update to 4.1.4 and retained 3.1.5. Its internal auditor reported a missing lockfile although the repository has one. The exact updater defect is unconfirmed; fixing Dependabot itself is unnecessary to remediate the locked dependency.

## Goals / Non-Goals

**Goals:** remove the identified affected version from the reproducible tooling graph, preserve conformance validation and generated output, and retain evidence for the actual candidate.

**Non-Goals:** generic dependency automation, permanent advisory parsers, new scanners, exploit testing against services, changes to business modules, and declaring all dependencies or the deployed image secure.

## Decisions

1. Add exactly `overrides: { 'ajv@8.17.1>fast-uri': '3.1.7' }` to the root pnpm-workspace.yaml, then regenerate pnpm-lock.yaml using pinned pnpm (`pnpm install --lockfile-only --no-frozen-lockfile`). This is a proposed command, not evidence of success. Parent-version scoping avoids affecting unrelated consumers and future Ajv versions. Do not edit lockfile integrity hashes by hand. Broader overrides, Ajv upgrades, direct dependencies, release-age/trust-policy exclusions, or unrelated dependency changes still require revised planning and approval. Existing supply-chain checks must stay enabled.
2. Keep specs deliberately skipped. Existing delivery reproducibility and SECURITY.md finding-lifecycle obligations already apply; introducing a new requirement solely for one package would add policy scope without a product need.
3. Use an observed affected-version baseline as RED, then actual resolver and advisory evidence as GREEN. Run existing conformance regressions rather than add a permanent version-spelling test. If a functional incompatibility is discovered, stop rather than modify product behavior under this dependency-only plan.
4. Preserve module ownership and secret boundaries. Schema/fixture inputs remain repository-local, runtime providers remain unchanged, and no integration credentials or production inputs are needed. Use only normally configured registry/GitHub access. Never publish raw authenticated scanner payloads.
5. Subtraction pass: no runtime component, shim, new test framework, scanner configuration, security exception, or automation is needed. Ordinary targeted update and interactive audit update were tried without remediating the lockfile; repeating them is not the chosen approach. A parent-scoped override is the next configuration-only intervention. A global fast-uri override affects unnecessary consumers; an Ajv upgrade expands dependency scope. Repeat this comparison before delivery.
6. Override ownership remains with repository maintainers. Reassess it whenever Ajv or fast-uri is updated or a new advisory appears. An exact pin can block later security patches; it is not permanent proof of safety. Remove the override only when a regenerated lockfile and fresh frozen install resolve a non-affected version without it, with the same compatibility checks. Removing or changing it belongs to that later reviewed dependency change, not an automatic expiry or suppression mechanism.

## Risks / Trade-offs

- Additional advisories may invalidate 3.1.7 → refresh upstream evidence before installation; if affected, stop and revise the target rather than silently broaden scope.
- A compatible semver range does not prove behavioral compatibility → perform frozen installation, resolve from Ajv's actual module context, run conformance and applicable repository gates, and compare generated outputs.
- Registry or supported execution may be unavailable → mark evidence blocked; do not change manifests or bypass permissions to work around it.
- The identified path is development tooling, not a demonstrated runtime attack → retain unresolved ownership until remediation without claiming false-positive status or full runtime safety.
- A dependency-only update does not trigger SECURITY.md's policy/scanner/gate/exception/release-security live-check condition by itself → do not fabricate a successful authenticated security check. If review identifies such impact, stop and reassess scope and access requirements.

## Migration Plan

After approval of this revised design, resume the existing security/remediate-fast-uri-tooling branch (currently a34b81ca98720925c497e2406fa4335d04bd0d93), checking current main and preserving planning files. Refresh the affected installed/locked version and current advisories, apply only the scoped override, regenerate the lockfile, perform a fresh frozen installation, and verify the resolved version and regressions. Diff acceptance permits only this override and its corresponding lockfile changes. No database or operator migration is expected.

Record safe evidence, exact SHA, commands, exit statuses, and limitations. Apply ends before archive; hosted checkpoint verification and archive follow their separately authorized phases. Then shape the final delivery commit, obtain all seven required checks and independent review for the exact PR head, merge, and confirm normal main/edge publication when authorized. No stable release.

Rollback is a reviewed revert. It restores the known affected dependency, so the finding becomes unresolved again; reverting is not remediation.

## Evidence References

- https://pnpm.io/settings/dependency-resolution#overrides (parent selector syntax; installed pnpm 11.19.0 remains the execution authority)

- https://github.com/hametovbr/media-finder/actions/runs/34212145092
- https://github.com/fastify/fast-uri/security/advisories/GHSA-5jgf-p345-68v8
- https://github.com/fastify/fast-uri/security/advisories/GHSA-qw65-cvwx-89v3 (3.x below 3.1.7)
- https://github.com/fastify/fast-uri/security/advisories/GHSA-58mr-gqgx-xq4g (3.1.6 specifically; not attributed to installed 3.1.5)
