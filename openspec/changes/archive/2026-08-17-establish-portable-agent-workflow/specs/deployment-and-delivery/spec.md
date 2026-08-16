## ADDED Requirements

### Requirement: Repository-owned agent workflow
The repository SHALL contain a self-sufficient project skill catalog for OpenSpec planning and apply, architecture decisions, implementation, debugging, review, public-contract evolution, module authoring, verification, publication, stable release, and skill maintenance. `AGENTS.md` SHALL retain project invariants and route work to those project-local skills without requiring a user-level skill installation or a specific workstation path.

#### Scenario: Continue work on another device
- **WHEN** a contributor or supported coding agent opens a clean repository checkout on another device
- **THEN** the checked-in `AGENTS.md` and `.agents/skills` provide the Media Finder-specific workflow, decision boundaries, and completion criteria without reading files from the previous device

#### Scenario: External skill is also installed
- **WHEN** a user-level skill overlaps a project-local Media Finder workflow
- **THEN** repository invariants and the project-local skill govern the project-specific procedure while system, developer, and explicit user instructions retain their normal precedence

### Requirement: Pressure-tested skill behavior
Each manually maintained project skill SHALL be concise, trigger-specific, and validated with a realistic application or pressure scenario. A new or materially changed skill SHALL have observed behavior without the target guidance and a repeated scenario with the target guidance explicitly applied. The evaluation record SHALL identify system, developer, global-skill, repository-instruction, project-skill, tool, workspace, and conversation context that the harness can expose.

An evaluation SHALL distinguish a historical observed RED, an isolated no-guidance baseline, a no-target-skill control, a contaminated control with overlapping guidance, and a post-skill forward test. A fresh conversation or omitted conversation fork SHALL NOT be described as isolated when other instruction sources remain available. A control that already complies SHALL be recorded as such rather than relabeled or repeatedly altered to manufacture failure. Literal source-text checks SHALL NOT substitute for behavioral evaluation, and contaminated controls SHALL NOT support causal claims beyond the behavior actually observed.

#### Scenario: Add a discipline skill
- **WHEN** a project skill is introduced to prevent architecture or workflow shortcuts under delivery pressure
- **THEN** its evidence records the historical or current control choice and rationalization, available instruction sources, the same scenario with the skill explicitly applied, observable decisions that distinguish compliance, and any limitation on attributing the result to that skill

#### Scenario: Fresh subagent can see overlapping guidance
- **WHEN** a pressure scenario uses a fresh conversation or omits parent conversation turns but the agent can still access global skills, repository instructions, project files, or the shared workspace
- **THEN** the run is labeled a contaminated or no-target-skill control rather than an isolated baseline, and a correct answer is not claimed as proof that the new skill caused the behavior

#### Scenario: Control already complies
- **WHEN** a no-target-skill control makes the expected decision without the new skill
- **THEN** the result is recorded honestly, historical observed RED may supply the failure evidence, and the scenario is not manipulated merely to obtain a failing answer

#### Scenario: Maintain generated OpenSpec skills
- **WHEN** the pinned OpenSpec CLI changes generated lifecycle skills
- **THEN** the repository regenerates and validates them through the CLI rather than editing their generated bodies manually

### Requirement: Reusable manually maintained guidance
Each manually maintained project skill and permanent routing rule SHALL express reusable decision conditions and procedures rather than hard-code the product version, release tag, workstation path, selected implementation, or historical incident current when the guidance was written. Release identifiers and incident-specific details MAY appear in release plans, change tasks, reference documentation, and labeled pressure scenarios, but SHALL NOT define a skill's purpose, trigger, or universal workflow. A release skill SHALL derive the intended version and tags from the approved release context and checked-in repository state.

#### Scenario: Use publication guidance for a later release
- **WHEN** a contributor invokes the publication skill for an approved future product release
- **THEN** the skill derives the intended version, previous tag, target commit, and moving tags from current repository and release context without requiring edits to replace an embedded earlier release number

#### Scenario: Learn from a historical auxiliary-tool failure
- **WHEN** a past custom-parser escalation is used to evaluate pragmatic architecture guidance
- **THEN** the incident remains a labeled example or pressure scenario while the skill applies the general complexity-rung, ownership, direct-execution, and subtraction rules to other auxiliary mechanisms as well

### Requirement: Exact-commit verification and release handoff
Project publication guidance SHALL bind local evidence, pull-request checks, merge, version preparation, GitHub Release creation, and GHCR publication to explicit commit identities. Unavailable local tools, a dirty worktree, a changed HEAD, a failed or skipped required check, or an unverified release workflow SHALL be reported and SHALL NOT be described as a complete release.

#### Scenario: Prepare a stable release after merge
- **WHEN** all change and release-preparation pull requests are merged to `main`
- **THEN** the release is created from the exact verified lockstep-version commit only after all seven required checks and the main-branch publish for that commit succeed

#### Scenario: Publish an immutable stable tag
- **WHEN** a stable GitHub Release is published
- **THEN** the agent waits for the release workflow and verifies the immutable SemVer tag, moving minor tag, `latest`, expected multi-architecture manifest, release URL, commit SHA, and clean final worktree before declaring completion
