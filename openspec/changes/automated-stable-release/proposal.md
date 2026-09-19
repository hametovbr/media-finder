## Why

Stable releases currently require manual lockstep version edits, a release PR, and GitHub Release creation. The owner works from a phone and needs one explicit version request to drive the complete verified publication without per-release human approval.

## What Changes

- Add manual GitHub Actions release preparation with an explicit stable product version, deterministic version updates, and a dedicated release PR.
- Automatically validate the generated candidate, merge through normal branch protection, verify the resulting main/edge commit, and create and publish a stable GitHub Release.
- Generate English release notes with an explicit automation disclaimer, traceable commit/PR links, and a link to the existing `docs/operations.md` guide. No separate authored-note format, manual notes-preparation step, editorial review, or AI review is required.
- Exempt only authenticated, deterministically verified release-preparation PRs from the process requirement for independent per-PR review. The automation itself and its later changes retain independent review.
- Preserve all seven verification contexts, strict branch freshness, conversation resolution, linear history, and the prohibition on bypass. The supplied protection screenshots show approvals disabled; no GitHub protection exception or migration is needed for that baseline.
- Require repository-scoped Administration read permission for authenticated inspection of main-branch protection; prohibit Administration write and protection bypass. Stop when protection cannot be verified or differs from the approved baseline.
- Confirm immutable and moving GHCR tags, platform manifests, digest and source provenance; support safe resumption after partial failure.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-and-delivery`: End-to-end stable release automation and the narrow generated-release review exception.

## Impact

Affected owners: `.github/workflows/ci.yaml`, `release.yaml`, reusable `verify.yaml`, repository release scripts, version/manifest/conformance artifacts, delivery validators/tests, and release operator documentation. A dedicated repository-scoped GitHub App installation supplies short-lived automation credentials; provisioning is a deployment prerequisite, not an existing capability of this chat connection.

No application runtime, API, SDK compatibility version, data schema, migration, provider integration, or deployment topology changes. No AI service, automatic semantic-version inference, ordinary-PR auto-merge, protection bypass, or automatic deployment to the owner's server. This change does not itself publish the next product release. General AGENTS.md and skill files remain unchanged; the canonical capability will express the user-authorized narrow exception.
