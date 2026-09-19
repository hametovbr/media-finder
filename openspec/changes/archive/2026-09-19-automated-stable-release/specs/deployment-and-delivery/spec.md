## ADDED Requirements

### Requirement: Explicit automated stable release request
An authorized repository writer SHALL be able to request a stable release from the GitHub web Actions interface by supplying a canonical product version. Normal execution SHALL require no subsequent human approval. Automation SHALL execute only trusted default-branch release logic, reject invalid or non-increasing versions, and serialize release requests. It SHALL NOT use a stable tag as the preparation trigger or deploy the application to an operator's server.

#### Scenario: Request from a phone
- **WHEN** an authorized writer submits a valid unused version with all deployment prerequisites configured
- **THEN** automation prepares a dedicated non-main branch and PR and continues through verification, merge and publication without per-release human review

#### Scenario: Reject unsafe input
- **WHEN** input is noncanonical, contains prerelease/build metadata or shell syntax, or selects an untrusted execution branch
- **THEN** the request fails before repository or registry mutation

#### Scenario: Concurrent or repeated request
- **WHEN** another version is active or the requested version already has preparation/publication state
- **THEN** automation rejects the conflicting request or reconciles the same authenticated operation without creating duplicate state or downgrading releases

### Requirement: Reproducible release candidate
Release preparation SHALL update all lockstep product versions and required version-derived conformance artifacts without dependency upgrades or API/SDK/schema-version changes. Before merge, automation SHALL reproduce the entire expected tree from the recorded base, requested version and captured release-note inputs. The review exemption SHALL require authenticated automation provenance, the expected repository/base and exact generated content; branch names, labels and changed-path allowlists alone SHALL NOT suffice.

#### Scenario: Prepare lockstep versions
- **WHEN** a release candidate is generated
- **THEN** all nine workspace distributions, first-party module manifests, UI package metadata, workspace lock entries and bound conformance versions/hashes agree and existing version/conformance checks pass

#### Scenario: Alter a release PR
- **WHEN** a candidate contains extra edits, unexpected dependency changes, altered generated values, or lacks authentic provenance
- **THEN** automation refuses automatic merge and reports the mismatch without overwriting those changes

### Requirement: English automatically generated release notes
Release notes and changelog output SHALL use English text and include `Automatically generated from repository history. Not editorially reviewed.` They SHALL identify the exact previous stable release and included history through the candidate, with traceable commit/PR links. They SHALL NOT require editorial or AI approval or claim migration, compatibility or rollback safety without explicit authored evidence. Non-English source titles SHALL NOT be copied as English prose. Notes SHALL link the existing `docs/operations.md` guide at the recorded candidate base commit. The release flow SHALL NOT require a separate authored-note format, per-change guidance input, or manual notes-preparation step. Automation SHALL NOT discover or summarize release-specific instructions from free-form PR text or additional authored files, or claim that such instructions are absent.

#### Scenario: Generate notes from mixed-language history
- **WHEN** included PR titles use multiple languages
- **THEN** the notes retain English framing, stable references and the disclaimer without automatic translation or unsupported safety conclusions

#### Scenario: Generate notes without separate authored input
- **WHEN** an authorized writer requests a release with only its version
- **THEN** notes contain the English template and disclaimer, the exact release range, traceable commit/PR links, and the recorded-base link to `docs/operations.md`, without requesting authored notes or asserting that release-specific instructions are absent

### Requirement: Protected automatic release merge
Only a verified generated release candidate SHALL be automatically merged. The seven existing verification contexts SHALL all succeed for the current candidate with trusted workflow provenance; current base freshness, resolved discussions and linear history SHALL remain enforced. Automation SHALL use normal protected merge with expected head identity, SHALL NOT approve its own PR, and SHALL NOT bypass or weaken repository protection. Automation SHALL authenticate and verify current main-branch protection against the approved baseline before exposing a candidate and immediately before merge. Missing access, unverifiable protection, protection drift or newly required approvals SHALL stop the operation.

#### Scenario: Stale or incomplete evidence
- **WHEN** a required result is missing, skipped, failed, cancelled, untrusted or belongs to an earlier head/base
- **THEN** automation does not merge or publish

#### Scenario: Preserve discussion and protection gates
- **WHEN** a release PR has unresolved discussions or protection disallows its merge
- **THEN** automation stops without resolving conversations, changing rules or invoking administrative merge

#### Scenario: Protection inspection is unavailable or detects drift
- **WHEN** authenticated protection inspection is denied, missing, malformed, or differs from the approved baseline
- **THEN** automation stops before the next candidate-exposure or merge action without using screenshots, skipping the check, changing rules or granting itself more access

### Requirement: Trusted release credential boundary
Release credentials SHALL be repository-scoped and unavailable to candidate code and untrusted event content. Privileged orchestration SHALL use trusted release logic and validate event, artifact and repository identities. Logs, notes and public artifacts SHALL NOT include credentials or integration data. Configuration SHALL permit repository-scoped Administration read for settings inspection, including branch protection, but SHALL NOT grant Administration write, authority to change repository settings, or branch-protection bypass to the release actor. Issued tokens SHALL have exactly the approved permissions and repository scope.

#### Scenario: Missing or malicious credentials context
- **WHEN** the required installation is unavailable or an event/artifact refers to an unexpected repository or candidate
- **THEN** privileged actions are refused and only safe diagnostics are emitted

#### Scenario: Validate the updated installation grant
- **WHEN** the owner reports granting Administration read to the App
- **THEN** activation remains blocked until installation token issuance, exact approved permissions and repository scope, and authenticated protection inspection succeed; missing permissions or Administration write are rejected

### Requirement: Verified stable publication and resumable failure
Automation SHALL bind the release tag to the exact accepted merged commit after successful verification and main/edge publication for that commit. It SHALL create and inspect a draft stable GitHub Release before publishing it. Completion SHALL require actual GHCR evidence for the immutable full-version tag, intended minor/latest tags, matching digest, both supported architectures and source revision. It SHALL never move an existing stable Git tag, overwrite an immutable image with a rebuilt digest, or replace newer moving tags with an older release. Failures SHALL report the completed boundary and permit identity-checked resumption.

#### Scenario: Main advances after release merge
- **WHEN** an unrelated commit reaches main while release verification is pending
- **THEN** release identity remains the accepted merged SHA and unrelated success cannot satisfy its gates

#### Scenario: Publish and verify
- **WHEN** publication finishes successfully
- **THEN** the summary identifies PR and merged SHA, release/workflow URLs, all three actual tags, digest and linux/amd64 plus linux/arm64 manifests with matching source provenance

#### Scenario: Recover from partial publication
- **WHEN** a timeout or failure occurs after a PR, merge, draft, release or image already exists
- **THEN** a retry verifies that existing state before continuing, preserves immutable identities and never reports success while required publication evidence is missing

#### Scenario: Reject conflicting existing release
- **WHEN** a version tag, release or image resolves to an unexpected target, or an older request would roll moving tags backward
- **THEN** publication stops without replacing the conflicting or newer state

### Requirement: Renewable automation authentication
Automation SHALL renew expiring installation credentials during long operations without human intervention, verify their App/repository scope, and keep them out of persisted artifacts. A failed renewal SHALL stop authenticated actions. A mutation with an uncertain outcome SHALL be reconciled before retry.

#### Scenario: Checks outlast the token
- **WHEN** a token approaches expiry while CI is pending
- **THEN** automation obtains a correctly scoped replacement and continues without requiring the owner to reconfigure the App

#### Scenario: Renewal fails
- **WHEN** a replacement token cannot be issued or has unexpected scope
- **THEN** automation stops safely without repeating an uncertain mutation

### Requirement: Bounded stale-base candidate replacement
An otherwise authentic unmerged release candidate whose base becomes stale SHALL be closed and replaced automatically by a new branch and PR from current main. The run that discovers the stale base SHALL reconcile merge state, record the terminal stale-attempt disposition and close the stale PR, then stop with `base_changed`; the operator SHALL re-dispatch the same canonical version, and that resumed operation SHALL prepare the replacement branch and PR rooted at current main with the next attempt number. Its evidence SHALL be retained, its candidate attempt SHALL become terminal, and the replacement SHALL require all seven checks for its own head/base. Automation SHALL permit at most three candidate attempts per repository/version operation, including across reruns. This behavior SHALL NOT overwrite manual edits or resolve discussions.

#### Scenario: Main advances before merge
- **WHEN** the current unmerged candidate becomes stale with remaining attempts and a trusted run discovers it
- **THEN** the discovering run reconciles merge state, records the terminal disposition and closes the stale PR without force-push, retains its branch and evidence, and stops with `base_changed`, so the operator re-dispatches the same canonical version and its resumed operation prepares the replacement candidate and notes from current main and obtains all seven checks for its own head/base

#### Scenario: Retry budget exhausted
- **WHEN** all three candidate attempts become stale
- **THEN** automation stops with a reported reason and a rerun does not reset the attempt count

### Requirement: Immutable recovery evidence
Before publishing a candidate, automation SHALL persist immutable preparation evidence outside its PR branch, including captured inputs, expected identities and trusted execution provenance. Recovery SHALL authenticate that evidence and subsequent checkpoints against their originating trusted workflow, repository, execution revision and content digest. PR metadata and artifact names alone SHALL NOT establish trust. Missing, expired, altered or ambiguous evidence SHALL block recovery without rebuilding expectations from mutable input.

#### Scenario: Resume after interruption
- **WHEN** a trusted execution stops after a GitHub side effect but before recording completion
- **THEN** recovery uses the prior immutable intent and exact observed identities to reconcile the result, or stops if the outcome cannot be established

#### Scenario: Missing or forged evidence
- **WHEN** the original artifact is unavailable or a replacement comes from an untrusted run or has a mismatched digest
- **THEN** automation does not merge or publish based on that evidence and reports the recovery blocker

## MODIFIED Requirements

### Requirement: Repository-owned agent workflow
The repository SHALL contain a self-sufficient project skill catalog for OpenSpec planning, apply, synchronization, archive, architecture decisions, implementation, debugging, review, public-contract evolution, module authoring, verification, publication, stable release, and skill maintenance. `AGENTS.md` SHALL retain project invariants, route work to those project-local skills, and distinguish completion of an individual authorized phase from completion of the overall work item without requiring a user-level skill installation or a specific workstation path.

For an OpenSpec-governed change, overall work completion SHALL require approved implementation and verification, synchronization of every applicable delta into canonical specifications, archive of the completed change, intentional commit shaping, branch push, pull request creation, successful required checks and review for the exact pull-request head, merge into `main`, and confirmation that `main` contains the delivered commit. For behavior-neutral work that legitimately bypasses OpenSpec, the inapplicable planning, synchronization, and archive gates SHALL be identified, while commit, pull-request, verification, and merge gates remain required. A phase boundary or unavailable external gate SHALL NOT be bypassed; the agent SHALL report the completed phase, the next required action or authorization, and the overall work item as incomplete or blocked.


A separately authorized verification phase MAY save an approved implementation as an explicitly non-final checkpoint on a non-main branch and open a draft pull request to obtain unavailable hosted verification evidence before synchronization/archive. This exception SHALL require a clean committed checkpoint, included active planning artifacts, a stated unresolved gate and candidate identity. It SHALL NOT permit publication during the planning or apply turn, merging, image/release publication, automatic archive, or declaring completion. Final delivery SHALL still synchronize/archive all applicable changes, shape the final commit set and rerun required checks and review for that final head.

#### Scenario: Continue work on another device
- **WHEN** a contributor or supported coding agent opens a clean repository checkout on another device
- **THEN** the checked-in `AGENTS.md` and `.agents/skills` provide the Media Finder-specific workflow, decision boundaries, phase status, next required gate, and overall completion criteria without reading files from the previous device

#### Scenario: External skill is also installed
- **WHEN** a user-level skill overlaps a project-local Media Finder workflow
- **THEN** repository invariants and the project-local skill govern the project-specific procedure while system, developer, and explicit user instructions retain their normal precedence

#### Scenario: Implementation phase finishes before archive
- **WHEN** all apply tasks and implementation verification are complete but the active change has not been synchronized and archived
- **THEN** the agent reports the implementation phase as complete, reports the overall work item as incomplete, identifies archive authorization as the next required boundary, and does not commit or publish a final delivery candidate that omits the applicable canonical-spec and archive results

#### Scenario: Complete behavior-neutral maintenance
- **WHEN** a behavior-neutral typo, formatting, comment, or safe repository-maintenance change legitimately bypasses OpenSpec
- **THEN** the agent records OpenSpec closure as not applicable and still completes intentional commit shaping, branch push, pull request verification, and merge confirmation before reporting the overall work item complete

For an authenticated generated release-preparation PR satisfying the automated release candidate contract, deterministic verification SHALL replace independent per-release review and human approval. This exception SHALL NOT apply to changes to automation itself, ordinary PRs, or candidates with unexpected changes. All other verification, merge and publication gates SHALL remain mandatory.

#### Scenario: Deliver a verified generated release candidate
- **WHEN** the dedicated release automation proves the complete candidate is its expected generated output and all required checks succeed
- **THEN** it proceeds without human or AI approval through normal protected squash merge and exact-commit publication verification

### Requirement: Exact-commit verification and release handoff
Project publication guidance SHALL bind local evidence, intentional commit shaping, branch push, pull-request checks, review, merge, version preparation, GitHub Release creation, and GHCR publication to explicit commit identities. An ordinary change SHALL be represented by one cohesive squashed commit or a small set of commits separated by logical area, not by incidental work-in-progress history. Unavailable local tools, a dirty worktree, a changed HEAD, a failed, pending, skipped, stale-SHA, or unavailable required check, an unmerged pull request, or an unverified release workflow SHALL be reported and SHALL NOT be described as a complete work item or release.


An explicitly labeled pre-archive evidence checkpoint MAY retain necessary work-in-progress commits solely for hosted verification. Its successful tests SHALL count only for the exact tested checkpoint and SHALL NOT replace the required checks or review for a later final delivery head.

#### Scenario: Publish an ordinary change
- **WHEN** an implementation and its applicable OpenSpec closure are ready for delivery
- **THEN** the agent shapes the intended logical commit set, pushes a non-`main` branch, opens a pull request, verifies every required check and required review against its exact head SHA, merges that verified head, and confirms the delivered commit is reachable from `main` before reporting overall completion

#### Scenario: Required pull-request evidence is not successful
- **WHEN** any required check or review for the exact pull-request head is failed, pending, skipped, unavailable, or superseded by another head
- **THEN** the agent does not merge or report overall completion and instead reports the work item as blocked or incomplete with the unresolved evidence

#### Scenario: Prepare a stable release after merge
- **WHEN** all change and release-preparation pull requests are merged to `main`
- **THEN** the release is created from the exact verified lockstep-version commit only after all seven required checks and the main-branch publish for that commit succeed

#### Scenario: Publish an immutable stable tag
- **WHEN** a stable GitHub Release is published
- **THEN** the agent waits for the release workflow and verifies the immutable SemVer tag, moving minor tag, `latest`, expected multi-architecture manifest, release URL, commit SHA, and clean final worktree before declaring completion

For an authenticated generated release-preparation PR satisfying the automated release candidate contract, deterministic verification SHALL replace independent per-release review and human approval. This exception SHALL NOT apply to changes to automation itself, ordinary PRs, or candidates with unexpected changes. All other verification, merge and publication gates SHALL remain mandatory.

#### Scenario: Deliver a verified generated release candidate
- **WHEN** the dedicated release automation proves the complete candidate is its expected generated output and all required checks succeed
- **THEN** it proceeds without human or AI approval through normal protected squash merge and exact-commit publication verification
