## Context

See `proposal.md` for motivation. The repository already contains six generated OpenSpec lifecycle skills and four short module/schema skills, but architecture, debugging, review, verification, publication, and skill-authoring behavior still depends on workstation-local guidance. The completed modular-core session also provides concrete failures that can serve as baseline evidence, most importantly the repeated expansion of a JavaScript delivery validator into a partial shell parser before the user redirected the design to an executable Python verifier.

The project uses `.agents/skills` as the cross-device skill location and `agents/openai.yaml` as optional Codex presentation metadata. OpenSpec remains the behavioral source of truth. The application package graph, runtime, database, HTTP contracts, CI contexts, and existing GitHub release workflow do not need another implementation path.

## Goals / Non-Goals

**Goals:**

- Make every Media Finder-specific planning, implementation, review, debugging, contract, publication, and release decision available from a clean checkout.
- Keep manually maintained skills reusable across future product versions, providers, failures, and implementation choices; use concrete history only as labeled examples and evaluation evidence.
- Turn the observed overengineering failure into an enforceable complexity circuit breaker rather than another advisory checklist.
- Retain small trigger-specific skills while keeping stable project invariants in `AGENTS.md` and mechanical checks in existing tests/CI.
- Prepare and publish the first stable image containing the modular architecture as `v0.2.0` after the workflow change is merged.

**Non-Goals:**

- Copy every upstream skill verbatim or require a Superpowers, GitHub, or personal-skill installation at runtime.
- Add an LLM evaluation service, prompt runner, content-substring validator, new workflow check context, release service, or source-language parser.
- Change product behavior, API/schema versions, database contents, package boundaries, or release workflow topology.
- Make project skills override system, developer, or explicit user instructions.

## Decisions

### 1. Keep a role-oriented catalog rather than a one-to-one upstream mirror

The checked-in catalog contains the six CLI-generated OpenSpec skills, the four existing domain skills, and seven manually maintained cross-cutting skills:

- `making-pragmatic-media-finder-decisions`;
- `developing-media-finder-changes`;
- `debugging-media-finder-failures`;
- `reviewing-media-finder-changes`;
- `evolving-media-finder-contracts`;
- `verifying-and-publishing-media-finder`;
- `maintaining-media-finder-skills`.

Each manual skill exposes a trigger-only description, a compact imperative workflow, red flags, and `agents/openai.yaml`. The historical audit records source influences by stable skill name and upstream version, never by device-local absolute path. This adapts the useful parts of architecture, TDD, debugging, review, verification, GitHub, pragmatic-decision, and skill-authoring guidance while removing conflicting `docs/superpowers`, plugin-only, and generic microservice assumptions.

Manual skill bodies are release- and incident-independent. They derive the current release version, selected module, contract version, and repository state from approved change context and checked-in sources rather than embedding the values used by this change. A historical failure may appear in `docs/agent-skills.md` as a pressure scenario or in a skill as a clearly labeled example, but it does not define that skill's purpose, trigger, or universal procedure. In particular, the pragmatic skill governs any unjustified increase in architecture or ownership level; it is not a skill whose purpose is to prevent one previously observed parser implementation.

Alternatives rejected: copying every upstream directory creates a large stale fork with overlapping triggers; putting every procedure in `AGENTS.md` makes the always-loaded contract long and prevents focused behavioral evaluation.

### 2. Separate invariants, judgment, and mechanics

`AGENTS.md` retains product/package/security invariants, authorization boundaries, the complexity circuit breaker, and a routing table. Skills contain conditional procedures and judgment. Existing Python/Node/OpenSpec tests and GitHub workflows enforce mechanical facts. `CONTRIBUTING.md` links the same routes without duplicating skill bodies.

No new script parses skill prose or claims to prove agent behavior. Normal YAML/frontmatter syntax can be checked with existing tooling, while actual skill behavior is evaluated through the recorded scenarios.

Alternative rejected: the previous literal-string skill validator passed when expected words existed but did not demonstrate that an agent made the intended decision.

### 3. Treat complexity category changes as an authorization boundary

The pragmatic skill uses the project ladder configuration → script/adapter → module → package → process/service. It runs before architecture approval, when implementation pressure suggests a higher rung, and before merge. Crossing any rung or introducing a new ownership category is not an implementation detail: apply stops, `openspec-update-change` compares simpler alternatives, and explicit approval is renewed. The previously observed regex-to-tokenizer/parser escalation is retained only as one evaluation example of this general rule.

TDD cannot expand scope. Every RED case must trace to an approved scenario or a reproduced defect in approved behavior. A mutation that only demands more knowledge of helper source spelling is evidence to reassess the helper, not an automatic requirement.

Alternative rejected: an advisory final subtraction pass occurs after most ownership cost is already sunk and allowed five consecutive parser-expansion rounds in the recorded session.

### 4. Store portable pressure evidence without building an evaluation platform

`docs/agent-skills.md` contains three classifications of historical skill use, the architecture evolution and interventions, provenance, routing, and compact scenario records. Each record contains the reusable prompt, available instruction sources, observed baseline decision/rationalization, expected decisions, forbidden decisions, post-skill outcome, and the limits of the causal claim.

A fresh conversation is not assumed to be a clean skill environment. A subagent that receives no conversation turns may still receive system/developer instructions, the global skill catalog, repository `AGENTS.md`, project-local skills, tools, and the shared workspace. Every evaluation therefore labels itself as one of: historical observed RED, isolated no-guidance baseline, no-target-skill control, contaminated control, or post-skill forward test. Historical observed failures are valid RED evidence. A fresh control that already complies is recorded honestly and is not relabeled as RED, does not prove the new skill caused the behavior, and is not repeatedly manipulated until it fails.

New and changed skills are evaluated one at a time. The primary pragmatic RED cites the already observed shell-parser history; fresh no-target-skill controls establish current behavior and contamination; the post-skill case is rerun with the checked-in skill explicitly loaded. When the available harness cannot remove overlapping global guidance, the evidence supports portability and regression claims only, not a controlled causal claim.

Required scenarios cover the shell-parser circuit breaker, independent UI without another service, a second static provider without discovery, Manual's narrow editor capability, processor wire compatibility, runtime/serialized safe-snapshot parity, cross-platform CI paths, exact-HEAD verification, and skill authoring without a content validator.

Alternative rejected: a custom LLM runner would add credentials, model/version variance, CI cost, and another maintenance surface without improving the reviewed textual evidence at the current contributor scale.

### 5. Strengthen existing domain skills through boundary failures found in review

The metadata skill adds bounded upstream reads, result and fan-out limits, finite portable payload values, defensive DTO validation, and runtime/serialized parity. The release skill requires canonical safe URL/GUID policy, bounds on validate/search/resolve, safe logger ownership, and aligned executable/serialized conformance. The download skill bounds authentication, destination, submission acknowledgement, and lookup responses while retaining exact correlation and timeout ambiguity. The metadata-schema skill requires pre-change wire characterization, an explicit stored-version policy, and a full producer-to-export/UI trace.

These are judgment and review requirements. Concrete limits remain in the SDK/spec artifacts rather than being duplicated numerically in skill prose.

### 6. Keep release guidance reusable and publish `v0.2.0` as a separate release instance

The publication skill defines a stable-release procedure without naming the target version of this change. It reads the intended product version and previous tag from the approved release context, `VERSION`, repository metadata, and verified Git history. The version-specific steps below are the one-time execution plan for this change and are not copied into `SKILL.md` or `AGENTS.md`.

The workflow-skill PR is merged first. A new branch from the resulting `main` updates the root `VERSION`, all nine Python distribution versions, built-in UI package version, four module manifest versions, workspace lock records, and the four manifest-hash-bound serialized fixtures from `0.1.0` to `0.2.0`. The private root tooling package remains `0.0.0`; control, processor, SDK contract, and schema versions do not change merely because the product version changes.

Release notes cover the complete `v0.1.0..release-commit` range, including the modular monolith, browser control boundary, environment-only integrations, static module SDK/conformance, and the breaking pre-release database reset. The release-preparation PR must pass the existing seven checks. After merge and successful `edge` publication, a draft stable GitHub Release targets the exact verified commit. Publishing it invokes the existing reusable verification and multi-architecture GHCR workflow. Completion requires verified `v0.2.0`, `0.2`, and `latest` tags for `linux/amd64` and `linux/arm64`.

Alternative rejected: tagging the workflow PR directly would leave workspace metadata at `0.1.0`; reusing or editing an immutable published release is prohibited.

### 7. Perform proportional verification

The workflow-only PR runs strict OpenSpec validation, documentation policy, skill metadata checks, pressure scenarios, formatting/diff checks, and the repository's required CI contexts. It does not invent a local full-runtime requirement when product code is untouched. The release-preparation PR runs lockstep/version tests, module/serialized conformance, all wheel builds, full repository verification, browser and production-image smoke because it is the exact source of a production image.

## Risks / Trade-offs

- **[Project skills can drift from OpenSpec]** → `AGENTS.md` declares OpenSpec authoritative and skill maintenance scenarios reject behavior that silently changes approved scope.
- **[Seventeen skill directories are a maintenance surface]** → Six are generated, four are existing domain guides, and seven consolidate multiple upstream roles; each manual skill remains short and has a distinct trigger.
- **[A skill can fossilize one release or incident]** → Manual skills contain reusable decision conditions and derive current identifiers from repository context; version-specific execution and historical examples remain in change tasks, release notes, and pressure evidence.
- **[Pressure evidence can become narrative rather than proof]** → Store reusable prompts, observable expected/forbidden decisions, classified baseline/control and post-skill outcomes, and instruction provenance; do not count prose presence as success.
- **[A fresh agent can inherit overlapping guidance]** → Record every available instruction source and classify the run; use historical observed RED where isolation is unavailable, never manufacture failure, and limit claims from contaminated controls to the behavior they actually demonstrate.
- **[The circuit breaker can pause legitimate implementation]** → Trigger it only on observable architecture-category, ownership, scope, or compatibility escalation; local implementation changes remain inside apply.
- **[A release can target the wrong commit]** → Bind version PR, seven checks, draft release, release tag, workflow run, GHCR manifest, and final handoff to recorded SHAs.
- **[The `v0.2.0` database reset can destroy pre-release data]** → Put the empty/new `/data` requirement and paired-image/data rollback warning prominently in release notes.

## Migration Plan

1. Create and approve this OpenSpec change from current `main`.
2. Record the historical audit and pressure-scenario format.
3. Add and evaluate the seven cross-cutting skills one at a time.
4. Update and re-evaluate the four domain skills one at a time.
5. Update `AGENTS.md` and contributor documentation only after every referenced skill exists.
6. Run the pragmatic independent review, strict checks, spec synchronization, and archive; merge the workflow PR after seven checks.
7. Create the separate `v0.2.0` lockstep version PR from updated `main`, regenerate manifest-bound fixtures, run the full release matrix, and merge after seven checks.
8. Create and review a draft `v0.2.0` GitHub Release targeting the exact version commit, publish it, and verify release workflow and GHCR manifests.

Rollback before publication is branch/PR rollback. After `v0.2.0` is published, source fixes use a new SemVer release; operators rolling back must restore the matching prior image and `/data` snapshot.
