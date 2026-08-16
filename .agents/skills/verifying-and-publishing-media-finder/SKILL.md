---
name: verifying-and-publishing-media-finder
description: Use when verifying a Media Finder branch, committing or publishing changes, opening or merging a pull request, preparing a stable release, or validating GitHub and GHCR results.
---

# Verifying and Publishing Media Finder

Bind every claim and publication action to one exact candidate. A passing result
from another HEAD, dirty tree, workflow revision, tag, or image digest is not
evidence for the current candidate.

## Verify the candidate

1. Record full HEAD, branch/ref, worktree and index status, tool versions, and the
   exact command before running it.
2. Run proportional local gates required by the affected OpenSpec task. Record
   exit codes and counts. Report unavailable network, browser, Docker, credentials,
   permissions, or platform coverage as `not run` or `blocked`, never passed.
3. Recheck HEAD and cleanliness after verification. Generated or uncommitted
   changes create a different candidate and invalidate completion claims.
4. Commit intentionally and push the exact branch. Open a PR with scope,
   verification, limitations, compatibility/rollback, and release impact.
5. Inspect all seven required `verification/*` checks and confirm each completed
   successfully for the PR head SHA. Do not substitute an arbitrary green run or
   hearsay status.

Merge only the verified head after required review. Record merge commit and
confirm `main`/edge publication for that commit when the workflow requires it.

## Prepare a stable release

Release preparation is a separate branch and PR from updated `origin/main`.
Derive the intended product version and previous tag from the approved release
context, root `VERSION`, workspace metadata, and verified Git history; never use a
version embedded in this skill.

Update every lockstep product-version location, module manifest, lock record, and
manifest-bound conformance hash. Do not change API, SDK, schema, or contract
versions merely because the product version changes. Generate notes from the
previous immutable tag through the candidate and include breaking migration/data
and rollback requirements.

Run version/lockstep tests, module and serialized conformance, all wheel builds,
full repository verification, browser checks, and production-image smoke. Merge
the release PR only after the same seven exact-SHA checks and successful main/edge
publish.

## Publish and verify

Create a draft stable GitHub Release targeting the exact verified main commit.
Verify notes, SemVer tag, target SHA, and non-prerelease state before publishing.
After publication, wait for the release workflow and verify:

- the immutable full-version GHCR tag;
- the intended moving minor and `latest` tags;
- expected architecture manifests;
- image digest provenance from the release commit;
- published release URL and successful workflow URL.

Never move, edit, or reuse an immutable stable tag. Fixes require a new approved
SemVer release.

## Final handoff

Report release URL, tag, commit SHA, image tags/digests/platforms, workflow and
check URLs, migration warning, unavailable local evidence, and clean worktree.
