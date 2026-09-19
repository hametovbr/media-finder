## Why

The manual publication entry point delivered by the previous change has three
runtime defects. A real repair request for `v0.5.0` produced the first two, and an
independent audit of the delivered revision found the third before it could block
the next attempt:

- the release-event publication job ran on the manual dispatch and failed with
  `unstable_release`. Its condition is `github.event.release.prerelease == false`,
  and on a dispatch `github.event.release` is an empty object, so GitHub's loose
  equality treats the absent field as `false` and the guard passes;
- the repair job could not publish the release revision. It set `GITHUB_SHA` in the
  step's `env:` block, but GitHub does not allow a workflow to override the
  `GITHUB_*` default variables, so the publisher kept the dispatch revision and
  refused with `checkout_revision_mismatch`;
- the publisher builds with `docker buildx build --cache-from type=gha --cache-to
  type=gha,mode=max` from a plain workflow step. The Actions cache backend needs
  runtime cache environment that a raw `docker buildx` step does not receive, so any
  publication that actually has to build an image fails. No other image build in
  this repository uses that backend.

None of the three is reachable by tests that assert workflow shape: shape cannot
express GitHub's expression coercion, the runner's reserved variables, or the
environment an action would have injected. No partial publication occurred — the
registry still has no `v0.5.0` tag, and every failure happened before a registry
mutation.

## What Changes

- Gate each publication entry point explicitly on the event it belongs to, so a
  guard can never pass because a field is absent for the other event.
- Apply the release-revision override at process level, where a reserved variable
  can actually be replaced.
- Remove the Actions cache backend from the publisher's build command, so building
  does not depend on environment the publishing step does not control; the
  repository's other image builds already avoid it.
- Extend the delivery policy so the entry-point regressions are rejected: the
  release-event job must name its event, and the manual job must carry the revision
  override in the command it runs rather than only in an environment block. Record
  in the publisher's tests that the build command carries no Actions cache backend.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-and-delivery`: the stable publication requirement gains an explicit
  rule that each entry point acts only for its own event, publishes only the
  revision it resolved, and does not depend on environment the publishing step
  cannot supply.

## Impact

Affected owners: `.github/workflows/release.yaml`, `scripts/release-publication.mjs`,
`scripts/release-publication.test.mjs`, `scripts/validate-delivery.mjs` and
`scripts/validate-delivery.test.mjs`. No controller or application change. The
already published `v0.5.0` tag, target commit and release object are untouched, no
image has been published for it yet, and nothing needs to be rolled back.

The repair path's `check-runs` query relies on public-repository read access; this
repository is public, and that dependency is recorded rather than papered over with
a permission the job does not need today.
