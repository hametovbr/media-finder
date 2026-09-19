# Automated stable release implementation checkpoint

This is an explicitly non-final implementation checkpoint for the active
[automated-stable-release change](../openspec/changes/automated-stable-release/proposal.md).
The owner requested completion of the current minimal-notes unit, a local commit
on a separate branch, and a pause. This checkpoint is not delivery, activation,
or a product release. General repository instructions and skills are unchanged.

## Resume context

- Original implementation base: `66774725cc1b02080dfa819f8fda3c066d3624d3`.
- The active [design](../openspec/changes/automated-stable-release/design.md),
  [requirements](../openspec/changes/automated-stable-release/specs/deployment-and-delivery/spec.md),
  and [tasks](../openspec/changes/automated-stable-release/tasks.md) are authoritative.
- The owner approved the minimal English release-notes contract: exact automatic
  generation disclaimer, captured commit/PR links and previous stable range,
  and a link to `docs/operations.md` at the recorded base commit. No authored-note
  format, free-form guidance discovery, or manual notes-preparation step.
- The owner reports installing the dedicated App and granting Administration
  read. This has not been verified through the actual installation token.
- Continue implementation only when the owner resumes work. Do not infer
  archive, push, merge, or stable-release authorization from this checkpoint.

## Implemented portions

The deterministic preparer updates lockstep versions and derived conformance
values, verifies the complete tree, preserves dependency/API/SDK versions, and
produces immutable English notes. Rollback guards cover unexpected filesystem
changes. The minimal-notes revision removes the unshipped authored-guidance path.

The controller has scoped token issuance, nested branch-protection inspection,
trusted CI/run-attempt evidence, draft/readback and publication checks, and
unreachable prepared Git objects persisted before branch exposure. Recovery
can discover preparation artifacts without local state and verifies the original
run attempt, actor, repository, App, digest and expiry. Preparation artifacts
remain valid after the producer run fails, is cancelled, times out, or is still
running; this does not weaken CI or publisher success gates. Duplicate intent
and conflicting repository state are rejected.

The stable publisher has registry fixture coverage for immutable digest reuse,
partial publication, moving-tag regression, platform and source provenance, and
ambiguous registry failures. The preparation workflow, delivery policy and
operator guide are present. These portions do not establish an operational
end-to-end release process.

## Next implementation work

Resume with authentic PR association and checkpoint recovery (tasks 2.2, 2.4,
2.5, 2.6 and 3.1). Authenticate the exact App bot author and complete PR repository,
branch and head identities. Reconcile an existing PR before creation, including
interruption after creation but before recording its association. Persist and
recover PR, stale-attempt and merged-SHA checkpoints through trusted artifacts.

Keep checkpoint-producing run/attempt/controller SHA distinct from the original
preparation. SDK upload readback must use the current producer run; downloads
must use the artifact's actual producing run. Validate schemas, metadata,
expiry, digest, chain links and live state before downstream mutations. Do not
make provenance checks optional to accommodate incomplete test fixtures.

Remaining dependent work:

- Isolated credential-free regeneration from the recorded base and captured
  inputs before merge; complete bounded history capture without silent truncation.
- Automatic stale-PR replacement with three attempts across reruns, preserving
  branches and persisting disposition before closure.
- One overall deadline and safe token-expiry/network-failure reconciliation.
- Production `--phase request --version <version>` composition. The preparation
  workflow already invokes this interface; the controller does not yet implement
  that phase. Do not activate or describe the workflow as usable.
- Correct final structured evidence and English summary. The current controller
  still reads `publication.tags` instead of canonical `actualTags`, and projects
  structured evidence a second time when formatting the summary, losing fields.
- Whole-change independent review and all remaining acceptance/delivery gates.

## Checkpoint verification

Accepted OpenSpec tasks: 1.1, 1.2, 1.3, 3.3, 4.1 and 4.2 (6 of 22).
The revised minimal-notes unit is complete. The controller parent tasks remain
open; their implemented portions are not whole-task acceptance.

The primary agent verified the frozen implementation with 20 preparer/workspace
Python tests and 74 controller/publisher Node tests. Python lint and formatting
also passed for the preparer and its tests. Documentation validation passed for 477 files, strict OpenSpec validation passed
for all 10 items, and delivery-policy validation passed.

## Verification limits

Focused checks for the completed portions do not replace whole-change checks or
live evidence. Earlier independent wheel builds, UI unit/build checks and module
conformance passed for their recorded implementation states. A full Python run
had a wheel-isolation installation timeout reaching PyPI; a focused reproduction
confirmed the network failure. Chromium installation failed at the browser CDN.
Docker/image smoke, current hosted browser evidence, authenticated repository
security, actual App event propagation and GHCR validation remain unavailable or
not performed. Disposable validation-repository access is a separate prerequisite.

Canonical specification synchronization, archive, final review, protected-branch
delivery and feature activation remain incomplete. No product release is part
of this checkpoint.
