## Context

See proposal.md for the failure and why the fix on `main` cannot repair it.
`release.yaml` is the sole stable image publisher and currently triggers only on
`release: published`, checking out `github.sha`, which for that event is the tagged
commit. `scripts/release-publication.mjs` derives its workspace from
`GITHUB_WORKSPACE` and reads the product version and `git rev-parse HEAD` from that
workspace, so the script's own location does not decide what is published.

## Goals / Non-Goals

**Goals:** let the current trusted publisher complete the image for an existing
stable release without moving its tag, without rebuilding an existing immutable
image, and without weakening any existing publication guard.

**Non-Goals:** introducing a second publisher or a second concurrency group,
changing the stable tag rules, changing the seven verification contexts, changing
the publisher's classification logic, and publishing anything for a tag that
cannot be verified as an existing stable release.

## Decisions

### 1. A manual entry point on the existing publisher, not a second workflow

`release.yaml` gains a `workflow_dispatch` trigger with a single tag input and a
main-only guard, keeping its existing release trigger. One publisher and one
concurrency group still serialize every stable publication, including hand-made
and repaired ones.

*Alternative considered:* a separate repair workflow. It would create a second
privileged publication path with its own group, breaking the approved
"sole stable image publisher" invariant and allowing two publications to race.

### 2. The workspace stays the release commit; the privileged logic comes from the dispatch revision

The job resolves the named tag to its commit, checks that commit out, and runs the
publisher script fetched from the dispatch revision on `main` from a runner
temporary path. Because the publisher reads its workspace from `GITHUB_WORKSPACE`,
the tree, `VERSION` and `HEAD` remain the release's, so the image still carries the
released source and its provenance, while the code that may delete or retag moving
pointers is the current trusted revision.

### 3. Resolve and validate the release before any registry access

A dedicated step resolves the named tag, requires an existing published release
that is neither a prerelease nor a draft, and requires the release commit's
`VERSION` to equal the tag. The publication step is skipped unless that step
succeeds, and the step exports the resolved commit, which the publication step
uses both as its checkout and as its event revision, so the publisher's identity
comparison is like-for-like rather than comparing the release to the dispatch
branch.

### 4. The delivery policy enforces the new entry point

`scripts/validate-delivery.mjs` currently pins the release workflow's trigger
shape. It gains assertions that the manual entry point exists only with a
main-only guard, a single tag input, a release-resolution step whose failure skips
publication, unchanged seven verification contexts and unchanged permission
separation, and that the publisher command and its immutable-state guard are
unchanged. Its tests cover the accepted shape and the rejected variants.

## Risks / Trade-offs

- A manual repair could be pointed at an arbitrary tag → the resolution step
  refuses anything that is not an existing published stable release whose tag
  equals the checked-out version, before any registry access.
- A newer script could change how an older tree is published → that is the point:
  only the privileged logic is current, the source and provenance remain the
  release commit, and the immutable-state guard still refuses to rebuild an
  existing image.
- Two publications of the same release could interleave → the existing
  repository-wide concurrency group already serializes both entry points.
