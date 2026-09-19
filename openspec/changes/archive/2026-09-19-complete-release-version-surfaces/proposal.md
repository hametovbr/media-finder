## Why

The archived `automated-stable-release` change made release preparation
deterministic, but its version-surface inventory was written from memory instead
of being derived from the repository's own release history. Comparing the v0.4.0
release commit `03947f1` (22 files) with the automated v0.5.0 candidate (21 files)
shows exactly two version-derived artifacts that the convention updates and the
automation omits:

- `tests/core/acquisition/test_module_runtime_integration.py`, which asserts the
  installed module version, so the `verification / unit` job fails and the
  controller correctly refuses to merge with `checks_not_green`;
- `apps/server/src/media_finder_server/control_gateway.py`, whose
  `build_version` default is what the running server actually reports, because the
  composition root never supplies it. The candidate would therefore publish
  version 0.5.0 while the server reports 0.4.0, and no test catches the drift.

A third defect makes the preparer unable to check itself: `tests/test_prepare_release.py`
builds its fixtures with `git archive HEAD` of the live checkout, so twelve of its
tests fail on any prepared tree and passed at the time only because the tree was
still at the pre-release version.

## What Changes

- Derive the preparer's version-surface set from the previous release commit rather
  than a hand-written enumeration, and cover every version-derived surface,
  including the server's reported build version.
- Make the affected module-runtime assertion derive the expected version from the
  first-party composition's own manifests instead of a literal, so a version bump
  cannot break it.
- Make the preparer's own tests version-agnostic by building fixtures from an
  explicit base version instead of `git archive HEAD` of the live tree.
- Add regression coverage that fails when a version-derived surface is missing from
  the candidate, so this class of omission cannot return silently.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-and-delivery`: the release-preparation requirement gains a complete,
  verifiable version-surface contract and the accompanying lockstep assertions.

## Impact

Affected owners: `scripts/prepare-release.py`, `tests/test_prepare_release.py`,
`apps/server/src/media_finder_server/control_gateway.py`,
`tests/core/acquisition/test_module_runtime_integration.py`, and the
release-preparation delivery-policy expectations. No application runtime behavior,
API, SDK compatibility version, data schema, migration, or deployment topology
change: the server continues to report the product version, and the fix keeps that
value correct instead of letting it drift. No product release is part of this
change.
