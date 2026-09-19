# Automated stable release implementation checkpoint

This records the archived
[automated-stable-release change](../openspec/changes/archive/2026-09-19-automated-stable-release/proposal.md)
and the hosted verification checkpoint obtained for it. The change is
synchronized and archived; delivery and activation remain separately authorized
subsequent phases. The workflow is not activated, the feature is not operational,
and no release can be run. General repository instructions and skills are
unchanged.

## Resume context

- Original implementation base: `66774725cc1b02080dfa819f8fda3c066d3624d3`.
- Checkpoint branch: `checkpoint/automated-stable-release-2026-09-16`, published
  to `origin` at commit `1e16ae3eb630cd0b848269b57045d6af30268bf6`; the local
  remote-tracking ref
  `refs/remotes/origin/checkpoint/automated-stable-release-2026-09-16` resolves to
  that commit. The published commit is only the checkpoint *base*: none of the
  controller work described below (request composition, checkpoint chain,
  operation-wide deadline, stale-base replacement, evidence fixes) is in it. That
  work is committed on the explicitly non-final branch
  `feat/automated-stable-release`, which exists to obtain the hosted verification
  evidence named under "Verification limits". The working tree has no untracked
  files.
- The archived [design](../openspec/changes/archive/2026-09-19-automated-stable-release/design.md),
  [requirements](../openspec/changes/archive/2026-09-19-automated-stable-release/specs/deployment-and-delivery/spec.md),
  and [tasks](../openspec/changes/archive/2026-09-19-automated-stable-release/tasks.md) are the
  authoritative record of the change, and the synchronized requirement text is now
  canonical in `openspec/specs/deployment-and-delivery/spec.md`.
- The owner approved the minimal English release-notes contract: exact automatic
  generation disclaimer, captured commit/PR links and previous stable range, and a
  link to `docs/operations.md` at the recorded base commit. No authored-note
  format, free-form guidance discovery, or manual notes-preparation step.
- The owner reports installing the dedicated App and granting Administration
  read. This has not been verified through the actual installation token.
- Delivery and activation are separately authorized subsequent phases: do not infer
  merge or stable-release authorization from this record.

## Implemented portions

The [operator guide](release-automation.md) documents the approved target
behavior. The implementation is committed on `feat/automated-stable-release`, the
change is synchronized and archived, and the delivered work covers OpenSpec tasks
2.1-2.6 and 3.1-3.5:

- **Preparer (1.1-1.3).** Deterministic lockstep version and derived-conformance
  regeneration with full-tree verification, unchanged dependency/API/SDK versions,
  rollback guards, and the immutable minimal English notes contract. The unshipped
  authored-guidance input and rendering path is removed.
- **Controller (2.1-2.6, 3.1, 3.2, 3.5).** The main-only dispatch entry point
  `.github/workflows/prepare-release.yaml` invokes
  `--phase request --version <version>`; the request phase composes discovery,
  preparation (attempt 1 or the next bounded attempt) and execution. Scoped App
  token lifecycle with per-issuance App, installation, repository and permission
  validation, including the required Administration read and rejection of
  Administration write. Mandatory authenticated release-PR identity (base/head
  repository IDs, base ref, base SHA, head ref, head SHA, exact App bot author)
  with reconcile-before-create, including interruption after PR creation but
  before the association is recorded. Isolated credential-free regeneration from
  the recorded base in a clean checkout that holds no write credentials. The
  exact seven-check gate (narrowed, duplicated or extended context sets are
  refused), authenticated protection revalidation before candidate exposure and
  immediately before the merge, mandatory merged-commit ancestry on `main`, and a
  normal expected-head squash merge with no bypass, administrative merge,
  approval, dismissal or auto-merge. Immutable preparation and checkpoint
  artifacts with producing-run provenance, digest/chain verification, actual
  expiry and crash reconciliation before and after side effects. One
  operation-wide deadline shared by every bounded wait; serialized requests;
  bounded listing reads that fail with an explicit error instead of truncating.
  The stale-base disposition records the terminal checkpoint, closes the PR and
  stops with `base_changed`; the documented same-version re-dispatch prepares the
  bounded replacement from current `main`, under a durable three-attempt limit
  that reruns cannot reset. History capture is bounded and fails with an explicit
  bound error instead of silently truncating the included range. Canonical
  structured evidence and the complete English workflow summary, including a
  blocked-evidence projection that preserves the failure's own safe next action.
- **Publisher (3.3, 3.4).** Registry fixture coverage for tag/version and
  digest/revision mismatch, missing architecture, partial pushes, immutable-tag
  reuse, older-release reruns and moving-tag regression. The publisher
  implementation was not changed; its existing behavior, including the manually
  published Release path, is exercised by 32 tests.
- **Delivery policy and operator setup (4.1, 4.2).** `pnpm delivery:validate`,
  the delivery-policy tests, and the operator guide.

These portions do not establish an operational end-to-end release process.

## Checkpoint verification

Independent verification and three independent review rounds ran on this change.
Rounds 2 and 3 returned `pass` with Critical 0 and Important 0 on the frozen
implementation, and round 4 reviewed the final delivery head and returned
`needs_revision` with Critical 0 and Important 2; both findings are resolved by the
follow-up commit recorded here.

- Frozen implementation candidate: `git diff | sha256sum` =
  `25ae122e242e9b26adef205bb08d80f34bee33baf913a570dd6f8e4f13c30495`.
- Final delivery head: `feat/automated-stable-release`, one cohesive commit over
  the checkpoint `1e16ae3eb630cd0b848269b57045d6af30268bf6`, clean worktree with no
  untracked files.

Gate results reproduced on the final head:

| Gate | Result |
| --- | --- |
| `node --test scripts/release-automation.test.mjs` | 113 tests, 113 pass, 0 fail |
| `node --test scripts/release-publication.test.mjs` | 32 tests, 32 pass, 0 fail |
| `pnpm delivery:test` (sandbox-observed) | 155 tests, 155 pass, 0 fail; `scripts/validate-delivery.test.mjs` alone 133/133 |
| `pnpm delivery:validate` | passed |
| `pnpm docs:check` | passed for 476 files |
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 pnpm spec:validate` | 9 passed, 0 failed (strict; nine specifications remain after this change was archived) |
| `uv run ruff format --check .` | 321 files already formatted |
| `uv run ruff check .` | passed |
| `uv run mypy` | passed (100 source files) |
| `uv run pytest` (sandbox-observed) | 628 passed |

Hosted evidence for the final delivery head (run `35448425645`, pull request #36):
all seven required contexts passed — `documentation`, `python`, `unit`,
`integration`, `contract`, `browser`, `image` — which covers wheel isolation and
production-image smoke. The downloadable browser evidence was inspected on this
head: `provenance.json` records `pullRequest.headSha`
`706cacc937c683f07c784bda346337377f8b9742`, base
`66774725cc1b02080dfa819f8fda3c066d3624d3`, the run id and attempt,
`testOutcome: success` and `missingCaptures: []`; the bundle contains 104 scenario
directories with 208 capture PNGs plus the Playwright report assets. The producing
checkout, not the head, is the synthetic pull-request merge commit `190a92a2…`,
which is expected for a pull-request run.

Authenticated security verification, captured on this candidate:

```console
$ pnpm security:verify -- --repository hametovbr/media-finder
$ node scripts/verify-repository-security.mjs -- --repository hametovbr/media-finder
Repository security verified: hametovbr/media-finder (secret scanning: enabled, push protection: enabled).
exit=0
```

Superseded evidence: the earlier "44 controller + 30 publisher" and "20 Python"
figures hold only for the pre-change revision, and the round-1 candidate
(`git diff | sha256sum`
`9dc14f5bb5e309efa612dd0680696c6234b976561b16ad92de317d23283eb5e0`) reported 108
controller tests; the current candidate is 113 + 32. The documentation check is
476 files on a quiet worktree whose status was confirmed with
`git status --short --untracked-files=all`; the 477 reported during implementation
did not reproduce and is recorded as an evidence mismatch. Two earlier rounds
counted the hosted browser evidence as 313 captures; that figure was wrong because
it included 105 Playwright report asset PNGs, and it is corrected above.

Sandbox caveat: `pnpm delivery:test` and `uv run pytest` were observed inside the
restricted sandbox and are not host-confirmed, because no wider execution boundary
was available in the delegated sessions. They are recorded as sandbox-observed,
never as host-passed, per [agent execution](agent-execution.md).

All 22 OpenSpec tasks are closed. Tasks 4.3 and 4.4 are closed on the hosted,
inspected and authenticated evidence recorded above. Tasks 4.5, 5.2 and 5.3 are
closed as explicit transfers to separately authorized phases, not as performed
work: disposable-repository validation of App-created event propagation, final
delivery through a reviewed pull request, and activation with proven App
credentials and an authenticated protection read remain outstanding, and the
archived task list states that in each case.

## Remaining work and next authorization

Synchronization and archive (5.1) are complete. The remaining gates are:

- **Delivery (5.2).** Pull request #36 on `feat/automated-stable-release` carries
  the final head with all seven required checks successful. It still needs a
  passing exact-head review and a protected squash merge with confirmed
  `main`/edge provenance, so merge remains **NO** at the time of writing.
- **4.5.** Disposable-repository validation of App-created PR, `main` and Release
  event propagation needs separate access authorization and a disposable
  validation repository. It is a recorded prerequisite of activation.
- **5.3.** Activation needs installation-token issuance, exact approved permissions
  and repository scope, and an authenticated `main`-branch protection read before
  the feature can be declared operational.

The next required action is the exact-head review and merge of pull request #36;
activation follows only after the App evidence required by 5.3 and the validation
recorded in 4.5 exist. A passing local review is not delivery readiness.

### Required design clarification

Independent verification accepted the re-dispatch reading of the OpenSpec 2.5
stale-base replacement ("automatically create") — its wording was "accept the
re-dispatch reading, **conditional on an explicit design note**", because the
design's same-run imperative and the delta's "SHALL be closed and replaced
automatically" "do not state a re-dispatch" and the operator guide's stale
paragraph "also omits that step". The change artifacts now record that sequence —
design decision 4, the delta's bounded-stale-base requirement and its "Main
advances before merge" scenario, and the operator guide's stale paragraph — and
code agrees with them. In a dedicated `openspec-update-change` turn the owner
confirmed this clarification and design decision 4 was tightened so that
"automatically create" explicitly means creation on the same-version resumption
after the terminal `base_changed` boundary, not in the run that discovers the
stale base; strict OpenSpec validation and the documentation check passed after
that edit. The revision made during the repair round was not preceded by a
recorded `openspec-update-change` invocation, so that earlier provenance remains
unresolved evidence. The archive that followed was separately authorized by the
owner and completed this change.

### Review findings

Review round 4 raised two Important findings, both resolved in the follow-up
commit recorded here: the authenticated `pnpm security:verify` result is now
captured in this document instead of being asserted without evidence and
contradicted elsewhere, and this handoff record now matches the committed and
archived state instead of describing an uncommitted candidate awaiting archive.

Review finding N1 (Minor) is also resolved. The two stale docblocks in
`scripts/release-automation.mjs` and the misleading comment on the legacy
next-action test in `scripts/release-automation.test.mjs` were corrected, and that
test now supplies a distinctive caller action and asserts it never reaches the
summary, so the assertion is discriminating instead of passing through an
unmapped-code fallback. The underlying behavior was never wrong; only the
documentation and the strength of the assertion were.

## Verification limits

Focused and local checks for the implemented portions do not replace the
whole-change, host and live gates. Independent wheel builds, production-image
smoke, the hosted browser evidence and `pnpm security:verify` are no longer
outstanding: they were obtained for the final delivery head and are recorded
above. Evidence that remains unavailable: the App installation token (issuance,
exact permissions and repository scope), the authenticated `main`-branch
protection read, live App-created PR/`main`/Release event propagation, and GHCR
manifest validation for a published stable release. Disposable
validation-repository access is a separate prerequisite.

Synchronization and archive are complete, and the seven required checks passed for
the final delivery head. The exact-head review and the protected merge, the
disposable-repository validation recorded in 4.5, and activation remain
incomplete. No product release is part of this record.
