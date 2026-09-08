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

## ADDED Requirements

### Requirement: Downloadable browser verification evidence
The existing browser verification job SHALL retain a downloadable test report and completed fixture screenshots for seven days on successful or failed test runs, provided the runner reaches evidence publication. Test failures SHALL remain failures; missing required evidence or failed publication SHALL prevent a successful evidence gate. Cancellation or setup failure SHALL be reported as incomplete evidence. The seven required verification contexts and read-only repository permissions SHALL remain unchanged.

#### Scenario: Inspect a successful browser run
- **WHEN** the browser suite and evidence publication succeed
- **THEN** a reviewer can download the report and required screenshots without running the application locally

#### Scenario: Browser assertions fail
- **WHEN** a browser assertion fails after some captures complete
- **THEN** completed evidence and the report remain downloadable and the job remains failed

#### Scenario: Evidence is unavailable
- **WHEN** setup, cancellation, upload, expiry or missing captures prevent access to required evidence
- **THEN** acceptance remains blocked and no passing report is inferred from absent artifacts

### Requirement: Candidate-bound fixture evidence
Evidence SHALL identify repository, tested checkout commit, triggering event commit, pull-request head and base commits when applicable, run ID and attempt, tool/browser version, test result and each screenshot's locale, viewport and scenario. Evidence SHALL use only deterministic fixture data and local or explicitly mocked resources, without real sessions, integration credentials or production data. Artifact collection SHALL be restricted to declared evidence outputs.

#### Scenario: Pull-request merge ref differs from head
- **WHEN** the workflow checks out a synthetic pull-request merge commit
- **THEN** provenance records both the actual checkout commit and pull-request head/base, and the evidence is not mislabeled as execution of the head commit alone

#### Scenario: Candidate changes
- **WHEN** head or base changes after capture
- **THEN** earlier evidence remains labeled with its original candidate and cannot establish acceptance of the changed candidate

### Requirement: Reviewable recovery captures
The evidence suite SHALL capture English and Russian UI at 360 and 1280 CSS-pixel widths. At each combination it SHALL include bootstrap failure, provider discovery failure, metadata-search failure and empty results, release-search failure and empty results, and locale-update failure. A pending search and successful keyboard recovery with visible focus SHALL also be captured at each combination. Captures SHALL include long unbroken query text, exclude unfinished asset loading and animations, and pair screenshots with overflow and keyboard/focus assertions. Screenshot existence SHALL NOT establish contrast or full accessibility compliance; reviewers SHALL inspect the actual artifacts and record remaining limitations.

#### Scenario: Review recovery from a phone
- **WHEN** a reviewer opens the completed evidence
- **THEN** filenames and report context identify every required locale/viewport/state, with readable screenshots and corresponding assertion results

#### Scenario: Capture a pending state
- **WHEN** a fixture request is deliberately held pending
- **THEN** the capture shows pending feedback at that settled UI state and subsequent explicit settlement permits the test to finish without an arbitrary timing assumption

### Requirement: Explicit preliminary verification handoff
A pre-archive hosted verification checkpoint SHALL require a user request received after the implementation turn and SHALL be labeled non-final in its commit/PR handoff. The agent SHALL preserve local work, use a non-main branch and a draft pull request, and record active changes and unresolved acceptance gates. The agent SHALL NOT merge it or treat checkpoint creation as delivery completion.

#### Scenario: Browser verification needs hosted execution
- **WHEN** an approved implementation lacks a runnable local browser and the user authorizes a subsequent verification phase
- **THEN** the agent may create the labeled checkpoint and draft pull request, inspect hosted evidence, and retain archive/final-head verification as outstanding gates

#### Scenario: Draft evidence passes
- **WHEN** the preliminary checkpoint produces passing tests and reviewable screenshots
- **THEN** verification is recorded for that candidate only, archive still requires its separate authorization, and final delivery still requires checks and review after synchronization/archive
