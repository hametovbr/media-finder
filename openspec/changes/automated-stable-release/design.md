## Context

Baseline: `66774725cc1b02080dfa819f8fda3c066d3624d3`, product version `0.4.0`. See proposal.md for scope. Existing owners are `.github/workflows/ci.yaml` (PR/main verification and edge), `verify.yaml` (seven checks), and `release.yaml` (stable GitHub Release event and multi-architecture GHCR publication). `tests/test_workspace_packages.py` inventories nine distributions, module manifests, the UI package version and workspace lock records; serialized conformance binds module versions and manifest hashes. Delivery policy is enforced by `scripts/validate-delivery.mjs` and its tests.

The owner's five supplied protection screenshots show main-only classic protection: PR required; approvals, code-owner approval and most-recent-push approval disabled; seven GitHub Actions verification contexts required with strict up-to-date enforcement; conversation resolution and linear history required; bypass forbidden; force-push and deletion disabled. Screenshot evidence is owner-supplied, not a successful authenticated protection API read. The read API returned 403 and the accessible rulesets collection returned an empty list. No protection edits are part of this design. Configuration drift is a runtime stop condition, not permission to bypass.

## Goals / Non-Goals

Provisioning update (2026-09-15): the owner reports the dedicated App has been created and installed, with repository variable `RELEASE_APP_CLIENT_ID` and secret `RELEASE_APP_PRIVATE_KEY` configured as instructed. This is owner-reported setup, not verified token issuance, repository scope, permissions or event propagation. Do not read or expose the private key. Validate access through the trusted workflow before activation; installation alone does not complete tasks 4.5 or 5.3.

**Goals:** One explicit request from the web Actions interface, automatic verified release PR and squash merge, exact-commit publication, recoverable failures, and machine-readable plus English human-readable completion evidence.

**Non-Goals:** AI/editorial review on each release, inference of semantic version or migration safety, changes to application behavior, automatic server deployment, general PR automation, new review exceptions in GitHub, rewriting tags, or changing AGENTS.md/global or project skills. The explicit owner-approved exception is recorded in this change and subsequently its canonical specification; ordinary agent delivery remains reviewed.

## Decisions

### 1. Bounded scripts and native workflows

Add `scripts/prepare-release.py` for deterministic product-version transformation and `scripts/release-automation.mjs` for bounded GitHub orchestration, with focused tests adjacent to existing version/delivery tests. Add `.github/workflows/prepare-release.yaml` using `workflow_dispatch` with an explicit `version` string and main-only execution. Use the existing pinned Python/uv and Node toolchains. No service, queue, database or LLM dependency is justified.

Use GitHub PR/ref/release objects for observable operation state and immutable Actions artifacts for trusted recovery inputs. A stable repository/version identity connects branch, PR, original base, prepared tree/head, merged SHA and release. Names or labels alone are never credentials. Reject prerelease/build metadata, noncanonical versions and versions not newer than both current product version and latest stable release. Reconcile authentic same-version state before applying increasing-version validation for new requests, so post-merge retries do not reject their own version. Conflicting state stops.

### 2. Deterministic candidate and notes

The preparer edits only root VERSION, the nine product pyproject version fields, builtin-ui package.json version, first-party module versions, workspace lock records, and corresponding serialized conformance version/hash fields. Use owning lock/conformance tooling where available; do not use global text replacement, upgrade dependencies or manually alter generated assets. Inventory any additional version-derived artifacts before accepting a tree. A clean regeneration must reproduce the full candidate tree from its recorded base and requested version.

Generate English notes with a fixed English template, commit/PR links and the exact previous stable tag and candidate range. Include `Automatically generated from repository history. Not editorially reviewed.` Avoid using untranslated PR titles as English prose; use stable IDs/links and English labels. Do not infer absence of migrations, breaking changes or rollback hazards. Link `docs/operations.md` at the recorded candidate base commit as the sole general upgrade, backup, and rollback guide. Do not discover, parse, summarize, or require per-change authored guidance from PR bodies or additional files; do not claim that such guidance is absent. Store notes in a version-specific `docs/releases/<version>.md` file so the regenerated tree covers their bytes too. The transformation's only external inputs are a captured, validated history/PR metadata snapshot; regeneration reuses that snapshot rather than mutable live titles.

Owner decision (2026-09-16): use this minimal notes contract. A structured PR marker and a dedicated authored-guidance directory were considered and rejected because they would introduce an additional contributor convention and manual input beyond the requested release flow. Remove the unshipped authored-guidance snapshot field, rendering path, and related expectations when applying this revision; retain the fixed guide link and immutable history inputs. No compatibility layer for that unshipped field is required. Generated `docs/releases/<version>.md` remains an output, not an authored input.

### 3. Trusted authorization without bypass

Use a dedicated GitHub App installed only on this repository: Contents write and Pull requests write; Actions, Checks, Metadata and Administration read. Administration read is authorized only for repository settings inspection, including branch protection; it is a repository-level read grant, not an endpoint-specific permission. Administration write, Workflows permission, protection bypass, checks-write permission and approval impersonation remain forbidden. Use RELEASE_APP_CLIENT_ID and RELEASE_APP_PRIVATE_KEY to issue repository-scoped installation tokens; never expose keys to PR jobs. Before every authenticated API batch, including long polling, renew a missing token or one with fewer than five minutes remaining. Validate App identity, installation, repository scope and permissions on each issuance. Never persist tokens. Renewal failure stops safely; an expired-token response during a mutation requires reading resulting state before retrying. App identity and installation/repository IDs are trusted configuration, not PR-controlled inputs.

App-generated PR, main push and published Release events can trigger existing workflows without GITHUB_TOKEN event suppression or per-PR workflow approval. Plain GITHUB_TOKEN plus chained manual approvals does not meet the agreed operator experience. PAT-based automation is rejected as an unnecessary user-bound credential.

The privileged controller executes only the trusted workflow/script revision captured from main at dispatch, checks out no PR code with credentials, and never runs shell text from inputs, titles, notes, artifacts or event payloads. Reproduction of candidate files runs without write credentials. Artifact paths/digests and API response identities are validated before use. The App must not auto-merge ordinary PRs, including similarly named branches or labels. Provisioning is required before rollout; missing credentials stops before side effects.

### 4. Guarded merge and bounded waiting

Read main-branch protection through `GET /repos/{owner}/{repo}/branches/main/protection` before candidate exposure and again immediately before merge. This endpoint requires Administration read for installation tokens ([GitHub documentation](https://docs.github.com/en/rest/branches/branch-protection#get-branch-protection)). Validate the returned protection fields, including nested `enabled` values, against the approved baseline: PR required, zero required approvals, no code-owner or latest-push approval, all seven required contexts bound to GitHub Actions, strict freshness, resolved conversations, linear history, administrator enforcement, and no force-push or deletion. Missing, denied, malformed or inconsistent evidence stops the operation; there is no optional protection-check switch or fallback to screenshots. The normal protected merge remains the final race guard. The controller never modifies repository settings.

The previous no-Administration design could not use this documented endpoint. The owner approved Administration read and reported adding the permission on 2026-09-16. Verify that the installation has accepted the updated grant, token issuance includes exactly the approved permissions, and an authenticated protection read succeeds before activation. Owner-reported setup is not live verification. A GraphQL alternative is not selected because its effective access with this App has not been verified; skipping inspection would violate the protection-drift requirement. No additional App, PAT, service or bypass is introduced.

Create a non-main branch and PR through the App. Record the generated head and full expected tree. Require same repository, expected App provenance, main base, exact regenerated content, no unhandled review requests/threads, and all seven successful verification jobs from the repository's trusted CI workflow and expected head/base integration candidate. Skipped, stale, cancelled, missing or untrusted-name-only checks do not pass.

Call ordinary squash merge with expected head SHA; never use admin merge or auto-resolve conversations. Strict protection remains the final race guard. If main advances before merge, reconcile whether merge already succeeded. If the candidate is unmerged and otherwise authentic, record a terminal stale_base attempt, close its PR and preserve its branch and evidence. Automatically create a new App-authored branch and PR rooted at current main with a new attempt number, regenerate notes, and rerun all seven checks for the new head/base. Never publish from an unmerged stale attempt, overwrite manual edits, or force-push. Permit three candidate attempts total, including the initial attempt, per repository/version operation; reruns must preserve the count. Exhaustion stops with base_changed_repeatedly. Unresolved discussions, tampering and other protection failures do not trigger this retry path.

Use a repository-wide release-controller concurrency group with cancellation disabled; reject a second active version rather than allowing out-of-order publication. Poll with bounded backoff and an overall deadline below the hosted job limit; retain state and emit a resumable timeout instead of waiting indefinitely. State is reconciled before every retry. No automatic retry of an unconfirmed mutation without reading whether it already succeeded.

### Recovery evidence

Before exposing a candidate branch or PR, upload an immutable Actions preparation artifact containing repository/App/installation IDs, operation and candidate-attempt IDs, trusted controller SHA, origin run ID and run attempt, base SHA, previous stable tag/SHA, requested version, full captured notes/history inputs and digest, expected tree and prepared commit SHA. Use unique artifact names and IDs, never overwrite. Persist later PR association, stale-attempt disposition and merged SHA as separate immutable checkpoints referencing the preparation artifact ID/digest. No credentials or private integration data belong in these records.

Recovery must discover records through the trusted repository workflow's runs, verifying main workflow identity, allowed initiating actor, recorded trusted controller revision, run/attempt, artifact ID and digest; a name or a locator from a PR is only a hint. Reject records from PR/fork workflows or unrelated runs. Verify bounded schemas, extraction paths and hashes before consuming bytes. GitHub artifact immutability plus authenticated run provenance establishes trust, not a self-declared hash in a modified PR. Scope credentials to the controller; candidate code cannot upload trusted records through this path.

Request 90-day retention, bounded by repository policy, and report actual expiry. Missing, deleted, expired, ambiguous or inconsistent evidence stops recovery; do not reconstruct trusted inputs from live mutable PR content. Check the checkpoint chain and live GitHub state before each mutation. A crash after a side effect but before its completion checkpoint may be reconciled from the prior durable intent and exact expected identities (for example prepared head and App-created PR or expected squash tree); ambiguous outcomes stop. A failed preparation upload admits no candidate publication. Persist the attempt identity before closing a stale PR so interruption cannot reset the three-attempt budget. No external state service is needed.

### 5. Exact merged commit and publication

Read the squash result, verify ancestry on main and equality to the accepted candidate tree. Wait for CI/main verification and edge publication belonging to that exact merged SHA; do not substitute another successful run or the current moving edge tag. A later ordinary main commit does not change the selected release SHA.

Create a draft GitHub Release with a new vX.Y.Z tag targeted at the verified merged SHA. Read back its tag target, notes, draft and prerelease fields before publishing through the App. Existing vX.Y.Z tags are never moved, deleted or reused for another target. Human-created releases retain the current entry point, but publication must also verify tag/version equality.

Keep `release.yaml` as the sole stable image publisher. Serialize all stable publications, including manually initiated releases, and prevent an older release from overwriting newer minor/latest pointers. A rerun must reuse a verified existing immutable image manifest rather than rebuilding and overwriting its tag; conflicting or unverifiable provenance fails closed. If publication partially succeeded, inspect each tag and repair only missing/intended moving pointers to the verified digest. Never roll back another newer release's pointers.

Completion requires inspecting actual registry manifests: vX.Y.Z, X.Y and latest resolve to the intended index digest, linux/amd64 and linux/arm64 platform manifests are present, and source revision provenance matches the release SHA. Attestation manifests are not runtime platforms. Emit release URL, workflow URL, PR/head/base/merged SHA, tags, digest and platforms. A published GitHub Release with a failed image job is partial, never successful.

## Risks / Trade-offs

- Dedicated App setup is additional one-time operator work → document exact permissions and stop until installed; no extra rights for this chat are assumed.
- Long CI or API outage → bounded wait and same-version state reconciliation; no duplicate release or blind retry.
- Mutable main/history metadata → capture exact identities and inputs; invalidate candidate evidence after any head/base change.
- Registry publication is not atomic across all tags → preserve immutable digest and repair moving tags only after provenance checks.
- Automatic notes are not a safety assessment → explicit disclaimer and a commit-pinned link to the existing general operations guide, with no invented compatibility assurances or claim to have assessed release-specific instructions.
- Any unexpected diff or protection change → stop; do not silently route to a weaker release path.

## Migration Plan

1. Implement and independently review scripts, workflows, tests and operator guidance through the ordinary OpenSpec lifecycle. Preserve the seven existing check contexts and protection settings.
2. Validate deterministic transformations and GitHub/registry error paths using fixture responses and local temporary Git repositories. Exercise real lifecycle events in an explicitly authorized disposable validation repository without publishing a product stable release.
3. Provision the dedicated App and validate repository-scoped access. Record that readiness is incomplete if the required access or live evidence is unavailable.
4. Enable the main-only dispatch workflow after implementation delivery and required authenticated security verification. Provide mobile browser launch and resume instructions.
5. Run the first real release only under explicit product-release authorization. Observe all completion evidence.

Rollback: disable new dispatch/controller execution and revoke its App credential; retain existing PRs, audit evidence, published releases and immutable tags. Resume manual release preparation under existing protections. No application data migration or data rollback is introduced.
