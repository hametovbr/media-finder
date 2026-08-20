## MODIFIED Requirements

### Requirement: Repository-owned agent workflow
The repository SHALL contain a self-sufficient project skill catalog for OpenSpec planning, apply, synchronization, archive, architecture decisions, implementation, debugging, review, public-contract evolution, module authoring, verification, publication, stable release, and skill maintenance. `AGENTS.md` SHALL retain project invariants, route work to those project-local skills, and distinguish completion of an individual authorized phase from completion of the overall work item without requiring a user-level skill installation or a specific workstation path.

For an OpenSpec-governed change, overall work completion SHALL require approved implementation and verification, synchronization of every applicable delta into canonical specifications, archive of the completed change, intentional commit shaping, branch push, pull request creation, successful required checks and review for the exact pull-request head, merge into `main`, and confirmation that `main` contains the delivered commit. For behavior-neutral work that legitimately bypasses OpenSpec, the inapplicable planning, synchronization, and archive gates SHALL be identified, while commit, pull-request, verification, and merge gates remain required. A phase boundary or unavailable external gate SHALL NOT be bypassed; the agent SHALL report the completed phase, the next required action or authorization, and the overall work item as incomplete or blocked.

#### Scenario: Continue work on another device
- **WHEN** a contributor or supported coding agent opens a clean repository checkout on another device
- **THEN** the checked-in `AGENTS.md` and `.agents/skills` provide the Media Finder-specific workflow, decision boundaries, phase status, next required gate, and overall completion criteria without reading files from the previous device

#### Scenario: External skill is also installed
- **WHEN** a user-level skill overlaps a project-local Media Finder workflow
- **THEN** repository invariants and the project-local skill govern the project-specific procedure while system, developer, and explicit user instructions retain their normal precedence

#### Scenario: Implementation phase finishes before archive
- **WHEN** all apply tasks and implementation verification are complete but the active change has not been synchronized and archived
- **THEN** the agent reports the implementation phase as complete, reports the overall work item as incomplete, identifies archive authorization as the next required boundary, and does not commit or publish a candidate that omits the applicable canonical-spec and archive results

#### Scenario: Complete behavior-neutral maintenance
- **WHEN** a behavior-neutral typo, formatting, comment, or safe repository-maintenance change legitimately bypasses OpenSpec
- **THEN** the agent records OpenSpec closure as not applicable and still completes intentional commit shaping, branch push, pull request verification, and merge confirmation before reporting the overall work item complete

### Requirement: Exact-commit verification and release handoff
Project publication guidance SHALL bind local evidence, intentional commit shaping, branch push, pull-request checks, review, merge, version preparation, GitHub Release creation, and GHCR publication to explicit commit identities. An ordinary change SHALL be represented by one cohesive squashed commit or a small set of commits separated by logical area, not by incidental work-in-progress history. Unavailable local tools, a dirty worktree, a changed HEAD, a failed, pending, skipped, stale-SHA, or unavailable required check, an unmerged pull request, or an unverified release workflow SHALL be reported and SHALL NOT be described as a complete work item or release.

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
