## Why

Release `v0.5.0` is published as a GitHub Release with no container image. The
stable publisher rejected a legitimately absent immutable tag as a registry
failure; that defect is fixed on `main`, but the fix cannot repair the release it
broke. `release.yaml` checks out `github.sha`, which for a release event is the
tagged commit `c91b44a`, so any rerun executes the pre-fix publisher and fails
identically. The workflow has no manual entry point, and the repository forbids
moving, deleting or reusing an immutable stable tag.

The operator guide already promises the missing capability: it instructs a
maintainer to "rerun that same guarded publisher run" and to rely on "the current
publisher's immutable-state guard". Nothing in the repository can do that today.

## What Changes

- Add a main-only `workflow_dispatch` entry point to `release.yaml` that takes an
  existing stable release tag, so the current trusted publisher can complete or
  repair that release's image.
- Resolve and validate the requested release: it must exist, be published, be a
  non-prerelease, non-draft stable release, and its tag must equal the checked-out
  version. Nothing is published for a tag that fails any of these checks.
- Publish with the trusted dispatch revision's publisher while the workspace stays
  the release commit, so the built image still carries the released source and its
  provenance, and only the privileged logic comes from the current trusted
  revision.
- Keep the existing release-event path, the seven verification contexts, the
  serialized publication concurrency group and the immutable-state guard
  unchanged, and extend the delivery-policy validator and tests to enforce the new
  entry point's guards.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-and-delivery`: the stable publication requirement gains an
  authorized recovery entry point for an existing stable release whose image is
  missing or incomplete.

## Impact

Affected owners: `.github/workflows/release.yaml`, `scripts/validate-delivery.mjs`,
`scripts/validate-delivery.test.mjs` and `docs/release-automation.md`. No
application runtime, API, SDK, schema, module or deployment-topology change; no
change to the stable publisher's tag rules, and no product version is introduced
by this change. The already published `v0.5.0` tag and release keep their identity
and target commit, and an existing immutable image is never rebuilt or
overwritten.
