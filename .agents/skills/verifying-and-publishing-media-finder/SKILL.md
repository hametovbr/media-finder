---
name: verifying-and-publishing-media-finder
description: Use when verifying a Media Finder branch, committing or publishing changes, opening or merging a pull request, preparing a stable release, or validating GitHub and GHCR results.
---

# Verifying and Publishing Media Finder

Bind every claim and publication action to one exact candidate. A passing result
from another HEAD, dirty tree, workflow revision, tag, or image digest is not
evidence for the current candidate.

## Verify the approved change

Before calling an OpenSpec implementation complete or ready to archive:

1. Run `openspec status --change <name> --json` and
   `openspec instructions apply --change <name> --json`. Read every reported
   context file, including proposal, specs, design, and tasks when present.
2. Check completeness (tasks and scenario coverage), correctness (behavior and
   tests match requirements), and coherence (implementation follows design and
   repository ownership). Attach concrete file, test, or command evidence.
3. Treat an incomplete task, missing requirement/scenario, failed required gate,
   or artifact contradiction as blocking. Return design/spec drift to
   `openspec-update-change` and implementation/test defects to
   `openspec-apply-change`.
4. Verification does not authorize sync or archive. Report readiness and stop;
   `openspec-archive-change` requires a later user request. Use
   `Verification phase: complete`, `Overall work: incomplete`, and name archive
   with applicable canonical-spec synchronization as the next authorization.

Do not finalize a delivery commit while an applicable change remains active or
its delta differs from the canonical spec. After the separately authorized
archive workflow returns successfully, continue ordinary publication unless the
user narrowed or stopped it or an external gate blocks progress.

## Verify the candidate

1. Confirm applicable OpenSpec changes are synchronized and archived. Inspect
   the complete diff and shape it on a non-`main` branch as one cohesive squashed
   commit or a small set of logically separated commits. Remove incidental WIP
   history before treating the branch as the final candidate; rewrite only the
   task-owned branch and use lease-protected force updates if it was already
   pushed.
2. Record full HEAD, branch/ref, worktree and index status, tool versions, and the
   exact command before running it.
3. Run proportional local gates required by the affected OpenSpec task. Record
   exit codes and counts. Report unavailable network, browser, Docker, credentials,
   permissions, or platform coverage as `not run` or `blocked`, never passed. Do
   not filter gate output through a pipeline unless `pipefail` preserves the
   originating command's status.
4. Recheck HEAD and cleanliness after verification. Generated or uncommitted
   changes create a different candidate and invalidate completion claims.
5. Push the exact non-`main` branch and open or update a PR with scope,
   verification, limitations, compatibility/rollback, and release impact.
6. Inspect all seven required `verification/*` checks and required review for the
   exact pull-request head SHA. Confirm every requirement completed successfully;
   failed, pending, skipped, stale-head, or unavailable evidence blocks merge. A
   head change invalidates earlier checks and review and restarts this step.

Merge only the verified head after required review. Fetch the resulting `main`,
identify the delivered commit produced by the repository's merge strategy, and
confirm it is reachable from `main`. Record the PR head, delivered commit, and
merge result; confirm `main`/edge publication for that commit when the workflow
requires it.

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

For ordinary changes, report exact commit SHA/ref, commands and counts, unavailable
evidence, push/PR state, exact-head checks/review, merge result, `main` ancestry,
and worktree status. Use `Overall work: complete` only after the delivered result
is confirmed on `main`; otherwise use `Overall work: incomplete` or `Overall
work: blocked` and name the unresolved gate. For releases, also report release
URL, tag, image tags/digests/platforms, workflow and check URLs, and migration
warnings.
