## 1. Deterministic release preparation

- [x] 1.1 Add failing tests for canonical version validation, increasing-version rules, nine-package/UI/manifest/lockstep updates, conformance hashes, unchanged dependencies/API/SDK versions and repeatability using temporary repository fixtures.
- [x] 1.2 Implement `scripts/prepare-release.py` and owning-tool regeneration; verify exact expected tree and reject any unexpected diff. Pass existing workspace-version and executable/serialized conformance suites.
- [x] 1.3 Add failing tests and implement the owner-approved minimal English notes contract: exact disclaimer, immutable history snapshot, previous-tag range, PR/commit links, and a recorded-base link to `docs/operations.md`. Remove the unshipped authored-guidance input/rendering path and its obsolete tests; align the controller and operator guide. Cover mixed-language titles, no separate manual notes input, reproducibility, and no inferred safety or guidance-absence claims. Verified against the revised 2026-09-16 contract with focused preparer and controller tests.

## 2. Trusted orchestration and merge

- [ ] 2.1 Add failing fixture tests for missing credentials, wrong repository/actor, forged release branch/labels, altered candidate content, untrusted workflow evidence and unsafe inputs.
- [ ] 2.2 Implement the main-only dispatch workflow and trusted controller, scoped App token lifecycle, credential-free regeneration and identity-bound branch/PR creation; prove PR code never executes with write credentials. Test token renewal before expiry, expiry during polling/mutation, failed refresh and exact permissions/repository-scope validation on every issuance, including required Administration read and rejection of Administration write.
- [ ] 2.3 Add failing tests for each of the seven check outcomes, head/base changes, unresolved conversations, changed protection, merge races and unexpected API responses. Cover denied/missing protection reads, nested enabled fields, malformed evidence, the approved baseline and revalidation immediately before merge.
- [ ] 2.4 Implement normal expected-head squash merge after all candidate gates; preserve strict freshness, linear history, all seven contexts and no-bypass behavior. Require authenticated protection inspection before candidate exposure and immediately before merge, with no optional bypass or settings mutations. Verify ordinary PRs cannot enter the release exemption.
- [ ] 2.5 Add failing tests and implement serialized requests, bounded waits, timeouts and same-version reconciliation across branch/PR/merge state; refuse tampered state and avoid force-push or duplicate operations. Cover automatic closure of stale PRs, new branch/PR creation from current main, all-check invalidation, and a durable three-attempt limit across reruns.

- [ ] 2.6 Add failing tests and implement immutable preparation/checkpoint artifacts: captured inputs and expected identities, trusted run provenance, ID/digest verification, actual expiry, tampering/deletion/expiry/forgery rejection, and crash reconciliation before and after side effects. Never accept PR-controlled replacement inputs.

## 3. Stable publication and recovery

- [ ] 3.1 Add failing tests for squash SHA/tree reconciliation, later main commits, wrong or missing main/edge evidence, draft target/notes mismatch and existing conflicting tags/releases.
- [ ] 3.2 Implement exact-main/edge gating, draft creation/read-back and stable publication through the App so the existing release workflow is triggered without human approval.
- [x] 3.3 Add failing registry fixture tests for tag/version mismatch, digest/revision mismatch, missing architecture, partial pushes, immutable-tag reuse, older release reruns and moving-tag regression.
- [ ] 3.4 Extend the sole stable publisher with serialization, immutable-digest preservation, safe partial-publication recovery and actual tag/platform/provenance verification. Keep standard manually published Releases supported under the same publication safeguards.
- [ ] 3.5 Emit an English workflow summary and structured evidence containing operation state, PR/head/base/merged SHA, release/workflow URLs, tags, digest, architectures and safe next action on failure.

## 4. Operator setup and validation

- [x] 4.1 Document one-time App installation and least-privilege permissions, secret placement, mobile dispatch, timeout/resume, protection-drift stop conditions and rollback. Document Administration read and installation acceptance of updated permissions; keep Administration write forbidden. Explicitly record that approvals are already disabled and no GitHub bypass or rule change is required.
- [x] 4.2 Extend delivery policy tests/validator to enforce trusted triggers, credential separation and preserved check contexts; run documentation checks and strict OpenSpec validation.
- [ ] 4.3 Run Python/Node tests, version and module/serialized conformance, independent wheels, full required repository verification and production-image smoke. Obtain current hosted browser evidence where local execution is unavailable.
- [ ] 4.4 Independently review the automation implementation and resolve findings; run authenticated security verification required by SECURITY.md. Missing supported access remains a blocker, not a waived gate.
- [ ] 4.5 Under separate access authorization, validate actual App-created PR/main/Release event propagation and recovery in a disposable validation repository. Record exact evidence and preserve target-repository secrets/protections; no production stable release is part of this test.

## 5. Delivery and activation

- [ ] 5.1 After authorized verification, synchronize the deployment-and-delivery delta and archive this change; preserve AGENTS.md and existing skill files.
- [ ] 5.2 Deliver the automation through the normal reviewed PR process with seven successful final-candidate checks; confirm merged main and edge provenance.
- [ ] 5.3 Validate the owner-reported target App setup with successful token issuance, exact approved permission and repository-scope evidence, and an authenticated main-branch protection read before declaring the feature operational. Keep activation blocked if credentials or required live evidence are unavailable; do not claim that fixtures alone prove end-to-end operation.

The first actual product release is a subsequent explicitly authorized operation, not a checkbox that silently creates a stable release during implementation validation.
