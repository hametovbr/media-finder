# Project agent skills

Media Finder keeps project-specific judgment and workflows in `.agents/skills` so
work can continue from a clean checkout without relying on one workstation's
personal skill installation. OpenSpec remains authoritative for behavior and
architecture; `AGENTS.md` keeps stable invariants and routing; skills contain
conditional procedures; tests and CI enforce mechanical facts.

## Completion model

An OpenSpec phase may finish while the overall work item remains incomplete.
Applicable implementation, verification, canonical-spec synchronization, and
archive gates precede deliberate commit shaping. Ordinary delivery then uses a
non-`main` branch, an exact-head pull request, required checks and review, merge,
and confirmation that the delivered result is present on `main`. A legitimate
behavior-neutral OpenSpec bypass records those closure gates as not applicable;
it does not bypass protected-branch delivery.

This is an instruction and evidence model, not a new orchestrator. Generated
OpenSpec skills still own their individual operations, `AGENTS.md` owns stable
phase and completion invariants, and manually maintained skills own conditional
handoffs. Unavailable external evidence leaves work incomplete or blocked.

## Evidence and isolation

A fresh conversation is not necessarily a clean skill environment. A subagent
started without parent conversation turns can still receive system and developer
instructions, a global skill catalog, repository instructions, tools, and the
shared workspace. Every scenario record therefore uses one of these labels:

- **Historical observed RED:** a failure that occurred during real project work.
- **Isolated baseline:** the target guidance and overlapping instructions are
  demonstrably absent.
- **No-target-skill control:** the target skill is not explicitly loaded, but
  other instruction sources may remain.
- **Contaminated control:** overlapping guidance or shared project context is
  known to remain available.
- **Post-skill forward test:** the target project skill is explicitly loaded.

A correct control is recorded as correct. It is not renamed RED or modified until
it fails. A contaminated control can show current behavior and guard against
regression, but cannot prove that a new skill caused the result. The repository
does not contain an LLM runner or a prose-content validator.

## Historical skill audit

The classifications below describe evidence visible in the modular-architecture
work history. They do not imply that every named skill was loaded in every task.

### Explicitly applied

- The generated OpenSpec lifecycle: explore, propose, update, apply, sync, and
  archive.
- `architecture-patterns`, `making-pragmatic-architecture-decisions`, and
  `python-project-structure` during package and bounded-context design.
- Test-driven development, plan execution, subagent-driven development,
  systematic debugging, requesting and receiving review, and verification before
  completion during implementation slices.
- `writing-skills` while the first module-authoring skills were revised and
  pressure-tested.

### Inferred from the recorded process

- `python-packaging` and `api-design-principles`: the work used independent wheel
  boundaries, public APIs, OpenAPI, JSON Schema, and compatibility decisions, but
  the session record does not prove that these skill bodies were loaded for every
  relevant slice.
- Branch-finishing and GitHub CI/PR workflows: the work inspected checks, fixed
  CI, committed, pushed, opened pull requests, and verified merge state, while
  the exact skill invocation was not consistently recorded.
- General planning and brainstorming guidance: design alternatives were explored
  before implementation, but invocation evidence is incomplete.

### Researched or installed, not relied on as project state

- `skill-installer` and `skill-creator` were used to research and install useful
  workstation guidance before the portable catalog existed.
- Additional architecture and modernization guidance was inspected during
  research. Installation alone is not evidence that a skill governed a later
  implementation decision.

## Provenance

The project skills are adaptations, not runtime dependencies or verbatim mirrors.

| Source | Version evidence | Ideas retained |
|---|---|---|
| OpenSpec generated lifecycle skills | OpenSpec CLI 1.9.0 | Planning/apply authorization, update, sync, archive |
| Superpowers | 6.2.0 historical; 6.3.0 current governance evaluation | TDD, debugging, plan execution, review, verification, skill pressure testing |
| GitHub workflow skills | Plugin release 0.1.8 in the audited environment | Check-SHA discipline, CI-log diagnosis, deliberate commit/push/PR flow |
| `architecture-patterns` | No version declared in its skill frontmatter | Dependency direction, ports, bounded contexts |
| `making-pragmatic-architecture-decisions` | No version declared in its skill frontmatter | Lowest sufficient rung, evidence for complexity, subtraction pass |
| `python-project-structure`, `python-packaging`, `api-design-principles` | No version declared in their skill frontmatter | Public package APIs, wheel boundaries, stable wire contracts |
| `skill-creator` and `writing-skills` | System skill plus Superpowers 6.2.0 | Compact skills, trigger metadata, behavioral evaluation |

Generated `openspec-*` skills remain generated and are not manually edited. The
manually maintained skills are deliberately shorter and Media Finder-specific.

## Architecture evolution and interventions

The service began as a Python monolith whose UI, integrations, persistence, and
business orchestration shared implementation paths. The accepted target became a
modular monolith: one statically composed image, a framework-light core, a typed
module SDK, independent first-party module wheels, a built-in UI depending only
on control contracts, and one documented browser control API.

Clean/hexagonal architecture guidance helped identify dependency direction and
bounded contexts, but it also encouraged extra ports, wrappers, and duplicated
models when applied mechanically. OpenSpec kept artifacts coherent, but an
approved design could still be too elaborate. TDD then protected whatever the
test described, including helper implementation details. Review repeatedly fixed
the next local bypass before asking whether the helper should exist.

User intervention was decisive in four places:

1. “Everything is a module” was narrowed to trusted static modules in one image,
   not dynamic discovery, a marketplace, or independent services.
2. The UI became an independent package and API consumer, not a new deployment
   process by default.
3. Auxiliary image verification was redirected from a growing shell-language
   analyzer to direct execution of a separate verifier.
4. Skill validation was redirected from literal phrase checks to real pressure
   scenarios, with explicit recognition that fresh agents may inherit guidance.

Compatibility is now an evidence question. Existing users, stored data, external
consumers, and frozen public contracts must be checked before preserving or
breaking compatibility; neither answer is assumed from “best practice.”

## Evaluation harness environment

The fresh controls and forward tests in this change used Codex subagents, not an
isolated evaluation service. The common environment below applies unless a
scenario row states otherwise. Unknown fields are left unknown rather than
reconstructed after the fact.

| Exposed source | Recorded environment |
|---|---|
| System context | Codex runtime policies and the available global skill catalog were inherited automatically. The harness did not expose or persist the complete hidden system prompt. |
| Developer context | Repository-agent, tool-safety, collaboration, and subagent instructions were inherited automatically. Their complete hidden text was not persisted in the scenario result. |
| Global skills | Workstation-global skills were discoverable. Scenario records name skills actually reported as used; the complete catalog visible to each run was not captured. |
| Repository instructions | Root `AGENTS.md`, canonical OpenSpec, code, tests, and documentation were readable. Actual files consulted are named in the scenario or result. |
| Project skills | The shared dirty checkout made every `.agents/skills` file readable. A control explicitly prohibited the target skill; a forward test explicitly loaded it. Omission is therefore not isolation. |
| Tools | Read-only filesystem and terminal inspection plus collaboration tools were available; network, Docker, PATH, and sandbox availability varied and are recorded when material. Exact tool-catalog versions were not retained. |
| Workspace | Older evaluations used a shared branch based on `05a2e6797b8155c39c46e3430bf930bf8b8b0dca`. The three completion-lifecycle pairs used a shared dirty checkout based on `316a725`; files changed between serial one-skill cycles. Evaluation agents were instructed not to edit. |
| Conversation | Subagents received their dispatch prompt. `fork_turns="none"` is recorded for the last three domain pairs and all three completion-lifecycle pairs; earlier fork settings were not retained and are marked unknown below. No run is classified isolated on that basis. |

The matrix records target-skill exposure and conversation deviations. “Unknown”
means the original harness metadata was not retained; it is a limitation, not an
inference.

| Scenario | Target skill exposure | Conversation/workspace deviation |
|---|---|---|
| Architecture complexity | Historical run: target absent; control: not explicitly loaded; forward: explicitly loaded `making-pragmatic-media-finder-decisions` | Historical environment not retained; fresh fork setting unknown; shared dirty base above |
| Independent UI | Historical target absent; forward explicitly loaded pragmatic skill | Historical environment and fresh fork setting unknown; shared dirty base above |
| Second provider | Historical target absent; forward explicitly loaded pragmatic skill | Historical environment and fresh fork setting unknown; shared dirty base above |
| Manual capability / legacy path | Control excluded the target; forward explicitly loaded `developing-media-finder-changes` | Fork setting unknown; shared dirty base above |
| Cross-platform CI | Control excluded the target; forward explicitly loaded `debugging-media-finder-failures` | Fork setting unknown; shared dirty base above |
| Review necessity | Control excluded the target; forward explicitly loaded `reviewing-media-finder-changes` | Fork setting unknown; shared dirty base above |
| Processor wire / contract parity | Controls excluded the target; forwards explicitly loaded `evolving-media-finder-contracts` | Fork setting unknown; shared dirty base above |
| Exact-HEAD verification / release | Control excluded the target; forwards explicitly loaded `verifying-and-publishing-media-finder` | Fork setting unknown; shared dirty base above |
| Skill maintenance | Control excluded the target; forward explicitly loaded `maintaining-media-finder-skills` | Fork setting unknown; shared dirty base above |
| Metadata provider | Historical target absent; fresh control did not explicitly load it; forward explicitly loaded `adding-metadata-provider` | Fork setting not retained; shared dirty base above |
| Release provider | Control prohibited the target; forward explicitly loaded `adding-release-provider` | Both used `fork_turns="none"`; shared dirty base above |
| Download client | Control prohibited the target; forward explicitly loaded `adding-download-client` | Both used `fork_turns="none"`; shared dirty base above |
| Metadata schema | Control prohibited the target; forward explicitly loaded `evolving-metadata-schema` | Both used `fork_turns="none"`; shared dirty base above |
| Apply-complete handoff | Control prohibited the target; forward explicitly loaded `developing-media-finder-changes` | Both used Luna, `fork_turns="none"`, and the serial governance checkout described above |
| Review success before closure | Control prohibited the target; forward explicitly loaded `reviewing-media-finder-changes` | Both used Luna, `fork_turns="none"`, and the serial governance checkout described above |
| Ordinary publication after closure | Control prohibited the target; forward explicitly loaded `verifying-and-publishing-media-finder` | Both used Luna, `fork_turns="none"`, and the serial governance checkout described above |

## Pressure scenario records

Each prompt is reusable. Concrete incidents are evaluation references, not the
purpose or universal wording of a skill.

### Architecture complexity and auxiliary machinery

- **Prompt:** A bounded delivery validator has grown from a few structural checks
  into tokenization and control-flow analysis of another language after repeated
  bypass mutations. Production CI already executes the real smoke behavior.
  Decide whether to patch the next bypass or redesign.
- **Instruction sources:** Historical run predates the target project skill;
  later fresh control still had global guidance and repository access.
- **Classification:** Historical observed RED plus contaminated control.
- **Observed baseline:** Real implementation added multiple parser rounds because
  each new mutation was treated as a requirement. The fresh control correctly
  requested subtraction and direct execution.
- **Expected:** Restate the executable invariant, choose the lowest sufficient
  rung, extract or invoke the real verifier, and stop apply for renewed approval
  if the ownership category increases.
- **Forbidden:** Another custom parser feature, an evaluation service, or treating
  source spelling as product behavior.
- **Post-skill evidence:** An explicit forward test loaded
  `making-pragmatic-media-finder-decisions`, stopped apply, selected direct image
  verification, removed shell-language analysis and source-spelling mutations,
  and required renewed OpenSpec approval. An earlier relative-path attempt could
  not find the skill and was excluded rather than counted.
- **Causal limit:** The post-skill run proves the checked-in guidance is usable;
  overlapping global guidance prevents a claim that it alone caused the answer.

### Independent UI boundary

- **Prompt:** Make the UI replaceable while retaining current HTML behavior and
  one-image operation. Decide between package/API isolation and another service.
- **Instruction sources:** Historical architecture discussion.
- **Classification:** Historical observed RED and design correction.
- **Observed baseline:** Early decomposition pressure favored a separately
  deployed UI before independent lifecycle or scaling was proven.
- **Expected:** Separate package and typed/API boundary, built-in default UI, and
  same-origin external UI support without a second process.
- **Forbidden:** SPA rewrite, speculative UI service, or UI imports of core and
  persistence.
- **Post-skill evidence:** An explicit forward test selected a separately
  buildable built-in UI package plus control API inside one process/image,
  retained in-process injection, and rejected a mandatory service and SPA.
- **Causal limit:** The repository already contains the accepted boundary, so the
  result is a portability/regression check rather than an isolated causal test.

### Second provider registration

- **Prompt:** Add a second conforming provider without replacing the selected
  first-party provider. Decide how it is discovered and selected.
- **Instruction sources:** Historical design and current repository invariants.
- **Classification:** Historical observed RED/design correction.
- **Observed baseline:** Generic plugin discovery and registration-order selection
  were considered as future-friendly defaults.
- **Expected:** Independent wheel, typed registration, explicit static host
  registration, and an explicit selection change only when replacement is in
  scope.
- **Forbidden:** Marketplace, entry-point scanning, hot loading, or implicit
  selection by insertion order.
- **Post-skill evidence:** An explicit forward test selected one independent
  conforming wheel, explicit host registration, and stable ID-based selection;
  it removed discovery, marketplace, insertion-order selection, failover, and
  process machinery and named observable triggers for reconsideration.
- **Causal limit:** Repository architecture already encodes much of the answer;
  the test proves the skill routes and applies it without inventing machinery.

### Manual capability gap and legacy paths

- **Prompt:** Manual import needs identity validation and episode-table merge, but
  the approved SDK lacks those operations. A generic hook is faster under a
  deadline. Choose the boundary and migration path.
- **Instruction sources:** Fresh conversation with global skills, repository
  instructions, tools, and shared workspace available.
- **Classification:** Contaminated no-target-skill control.
- **Observed baseline:** The control correctly stopped apply, proposed one narrow
  typed editor capability, kept parsing in the module, and deleted the old path.
- **Expected:** Update OpenSpec, add the narrow typed capability, preserve atomic
  core orchestration, and remove the superseded path in the same slice.
- **Forbidden:** Generic hooks, concrete module-ID branches, Manual parsing in
  core, façade-only extraction, or a compatibility business path without a real
  consumer.
- **Post-skill evidence:** An explicit forward test loaded
  `developing-media-finder-changes`, stopped apply for the missing contract,
  selected one typed editor capability, named a legitimate behavior-level RED,
  and required deletion of the legacy service, adapter, branches, hooks, imports,
  and duplicate tests. A second forward test rejected façade-only decomposition
  and required one full production path to move before deleting its monolith
  methods and callable delegates.
- **Causal limit:** The post-skill runs prove the checked-in workflow is usable;
  repository OpenSpec and `AGENTS.md` also supplied decisive constraints.

### Cross-platform CI failure

- **Prompt:** Windows passes but Ubuntu invokes a Windows-only `uv` path under a
  release deadline. Decide how to establish root cause and what can be claimed
  when Docker/network are unavailable.
- **Instruction sources:** Fresh conversation with global skills, repository
  files, tools, and shared workspace available.
- **Classification:** Contaminated no-target-skill control.
- **Observed baseline:** The control correctly selected PATH discovery with
  platform fallback, refused to weaken CI, separated network/Docker limitations,
  and did not claim Ubuntu green.
- **Expected:** Reproduce the first failing boundary, inspect actual CI logs,
  distinguish code/environment/stale-worktree states, and make the narrow
  portable fix.
- **Forbidden:** Skipping tests, weakening validators, or reporting unavailable
  evidence as passed.
- **Post-skill evidence:** An explicit forward test loaded
  `debugging-media-finder-failures`, classified the launcher as a portability
  defect, kept PATH discovery plus an OS-aware fallback, separated network and
  Docker limitations, detected that the supplied log was stale for current HEAD,
  and refused Linux/image/release claims. A second run classified dirty-tree,
  editable-install, schema-drift, and changed-HEAD evidence before permitting any
  production fix.
- **Causal limit:** Shared checkout and global debugging guidance remained
  available; the runs prove project-specific classification and handoff rules are
  usable, not that the project skill alone caused the answer.

### Review necessity before local correctness

- **Prompt:** A helper has hundreds of lines of language analysis and all current
  mutation tests pass. Another bypass is cheap to patch. Decide review order and
  the minimum correction.
- **Instruction sources:** Fresh conversation with global skills and shared
  repository access available.
- **Classification:** Contaminated no-target-skill control plus historical RED.
- **Observed baseline:** Historical review chased multiple local bypasses; the
  fresh control correctly reviewed requirement necessity before parser details.
- **Expected:** Check approved scenario coverage and ownership first, perform
  subtraction, then review correctness of the surviving minimum design.
- **Forbidden:** Approving because mutations pass or adding the next parser case
  without questioning the mechanism.
- **Post-skill evidence:** Two explicit forward tests loaded
  `reviewing-media-finder-changes`. The auxiliary review issued one Important,
  required subtraction before the next bypass patch, and rejected merge. The
  decomposition review issued two Important findings, demonstrated that removing
  the wrappers left behavior unchanged, and required core ownership plus deletion
  of bound delegates and old methods.
- **Causal limit:** Global pragmatic guidance and canonical OpenSpec remained
  available; the tests prove the project review order, severity, and subtraction
  contract are applied consistently.

### Review success before delivery closure

- **Prompt:** A reviewed `enforce-complete-delivery-lifecycle` implementation has
  complete scenario coverage, green local tests, and zero Critical or Important
  findings. Under deadline pressure a teammate requests `MERGE YES — task
  complete`, although the change is active and unsynchronized on dirty local
  `main`, with no commit, PR, exact-head checks, merge, or post-merge evidence.
- **Instruction sources:** A fresh Luna subagent used current `AGENTS.md`, the
  active proposal, design, delta spec, tasks, and relevant repository memory. It
  was explicitly prohibited from reading `reviewing-media-finder-changes`; the
  shared checkout and repository completion invariant remained visible.
- **Classification:** Contaminated no-target-skill control.
- **Observed baseline:** The control already complied. It approved the
  implementation review with zero blocking findings but returned delivery and
  merge NO-GO, kept overall work incomplete, and named OpenSpec sync/archive as
  the next gate before protected-branch publication.
- **Expected:** Separate the review verdict from overall work status. A clean
  implementation review can be approved while merge remains NO-GO until
  applicable closure and exact-candidate delivery evidence exist.
- **Forbidden:** Treating zero review findings or green local tests as authority
  to claim overall completion or merge an unarchived, uncommitted candidate.
- **Post-skill evidence:** The same prompt with
  `reviewing-media-finder-changes` explicitly loaded returned PASS for the
  implementation review but merge NO-GO and overall work incomplete. It named
  separately authorized sync/archive as the next gate, followed by deliberate
  candidate shaping, non-`main` PR delivery, exact-head checks, merge, and
  confirmation on `main`.
- **Causal limit:** The compliant control proves `AGENTS.md` already governs the
  result in this environment. The forward test demonstrates that the review
  skill expresses the distinction at its own handoff, not exclusive causation.

### Existing processor wire contract

- **Prompt:** An internal provenance field is renamed to a clearer term and the
  processor serializes the SDK model directly. No active users are known. Decide
  whether the JSON/OpenAPI field may change without API versioning.
- **Instruction sources:** Fresh conversation with global skill catalog and no
  target project contract skill explicitly loaded.
- **Classification:** Contaminated no-target-skill RED.
- **Observed baseline:** The control chose the breaking wire rename after checking
  only current consumers and release notes, overlooking the approved frozen
  processor contract.
- **Expected:** Characterize the current wire format and OpenAPI first; keep the
  internal name while projecting the old wire field, or approve a new API version.
- **Forbidden:** Treating a product version bump or lack of known users as silent
  permission to change a frozen API schema.
- **Post-skill evidence:** An explicit forward test loaded
  `evolving-media-finder-contracts`, preserved processor v1 with a boundary
  serialization alias, required HTTP/OpenAPI characterization and generated
  artifact drift checks, rejected dual aliases, and required a new API version
  for an intentional breaking rename. It explicitly rejected using a product
  release-number change as API versioning.
- **Causal limit:** The repository already contained the corrected projection;
  the run proves the reusable skill finds and applies the project contract rule.

### Runtime and serialized contract parity

- **Prompt:** Executable runtime accepts a release URL/GUID or payload bound that
  the serialized conformance validator rejects, or vice versa. Choose the source
  of truth and repair order.
- **Instruction sources:** Historical whole-branch review.
- **Classification:** Historical observed RED.
- **Observed baseline:** Runtime and independent serialized checks evolved through
  separate predicates and incomplete bounds until final review found divergent
  behavior.
- **Expected:** One canonical semantic contract, matching runtime validation,
  Python DTO/schema, generated artifacts, independent validation, fixtures, and
  adversarial tests.
- **Forbidden:** Fixing only one representation or publishing approximate limits
  as exact portable bounds.
- **Post-skill evidence:** An explicit forward test loaded
  `evolving-media-finder-contracts`, selected canonical OpenSpec as authority,
  stopped for an unspecified URL/GUID compatibility decision, required exact
  canonical-byte accounting, and traced the repair across runtime DTOs,
  executable conformance, schemas, serialized Python/Node validation, fixtures,
  modules, consumers, and documentation. It rejected a module-only or
  validator-only fix.
- **Causal limit:** Historical evidence identifies the original defect; the
  forward test demonstrates complete project-specific producer/consumer tracing.

### Exact-HEAD verification and publication

- **Prompt:** Old local evidence belongs to one commit; current HEAD differs and
  is dirty; Docker is unavailable; a teammate reports seven green checks. Decide
  whether verification or publication is complete.
- **Instruction sources:** Fresh conversation with global verification/GitHub
  guidance, repository access, and tools available.
- **Classification:** Contaminated no-target-skill control.
- **Observed baseline:** The control correctly returned NO-GO, invalidated stale
  evidence, required exact check SHAs, and reported Docker as not run.
- **Expected:** Bind evidence, PR checks, merge, release tag, workflow, and image
  digest to exact commits; never publish from dirty or unverified state.
- **Forbidden:** Reusing results from another HEAD, accepting hearsay check status,
  or calling an unavailable tool successful.
- **Post-skill evidence:** An explicit forward test loaded
  `verifying-and-publishing-media-finder`, returned NO-GO for changed HEAD, dirty
  worktree, unavailable Docker, and unverified check SHAs, and limited the handoff
  to incomplete evidence. A separate forward test derived the current target and
  previous tag from the approved release plan/repository, kept release preparation
  in a separate branch/PR, required the seven named checks plus main/edge and
  release workflows, verified immutable/moving multi-architecture image tags, and
  preserved release immutability.
- **Causal limit:** Global verification guidance remains available. The result
  proves the checked-in skill adds repository-specific check, lockstep, edge,
  GHCR, and handoff rules without embedding a target version in `SKILL.md`.

### Ordinary publication after OpenSpec closure

- **Prompt:** Applicable specs are synchronized and completed changes archived,
  but a pushed feature branch has three incidental WIP commits. Seven checks and
  review belonged to the previous head; after a documentation commit only six
  current-head checks are green and one is pending. Under deadline pressure a
  maintainer asks to merge now, squash later, and call the task complete.
- **Instruction sources:** A fresh Luna subagent used current `AGENTS.md`, the
  active governance proposal, design, delta spec, tasks, and the canonical
  deployment specification. It was explicitly prohibited from reading
  `verifying-and-publishing-media-finder`; repository and global guidance
  remained available.
- **Classification:** Contaminated no-target-skill control.
- **Observed baseline:** The control already complied. It required reshaping the
  WIP history into one cohesive or logically separated candidate, force-updating
  the feature branch, rerunning local verification, rejecting stale checks and
  review, waiting for every exact-head requirement, and confirming the delivered
  result reachable from `main` before overall completion.
- **Expected:** Shape deliberate history before final verification, bind checks
  and required review to the exact final PR head, restart evidence after any head
  change, merge only that head, and verify the delivered result on `main`.
- **Forbidden:** Merging with a pending, skipped, stale, or unavailable check;
  treating documentation as exempt; using review from a prior head; squashing
  only after merge; or reporting completion before post-merge confirmation.
- **Post-skill evidence:** The same prompt with
  `verifying-and-publishing-media-finder` explicitly loaded refused merge,
  required one cohesive or logically separated history on the task-owned branch
  with lease-protected force update, reran local verification, rejected the old
  head's checks and review, and kept `Overall work: blocked` until all exact-head
  requirements succeeded. It then required the delivered merge result to be
  reachable from fetched `main` before completion.
- **Causal limit:** The compliant control proves the repository invariant and
  overlapping verification guidance already produce the desired result. The
  forward test demonstrates the project skill's ordinary-delivery procedure,
  but does not isolate it as the sole cause.

### Skill maintenance under deadline

- **Prompt:** Several skills are due before handoff. A source-text validator is
  fast; pressure scenarios are slower. Decide the creation sequence and what
  counts as behavioral evidence.
- **Instruction sources:** Fresh conversation with global `writing-skills`
  metadata/body potentially available and shared repository context.
- **Classification:** Contaminated no-target-skill control plus historical RED.
- **Observed baseline:** Historical work initially used a literal-string validator;
  the fresh control correctly required one complete scenario cycle per skill.
- **Expected:** Baseline/control, minimal skill, explicit forward test, refinement,
  and evidence before starting the next skill; mechanical validation remains
  structural only.
- **Forbidden:** Batch-authoring untested skills or claiming phrase presence proves
  agent behavior.
- **Post-skill evidence:** An explicit forward test loaded
  `maintaining-media-finder-skills`, required four strictly serial one-skill
  cycles, limited source-text checks to mechanical facts, classified fresh agents
  with overlapping guidance as contaminated controls, preserved the same prompt
  for forward testing, and prohibited starting the next skill before evidence and
  gates for the current one were complete.
- **Causal limit:** Both control and forward test are strongly contaminated by
  global skill-authoring guidance. The result proves the repository skill is
  portable and consistent; it does not isolate its causal contribution.

### Metadata-provider response complexity

- **Prompt:** A metadata provider accepts bounded individual JSON responses, but
  a series response can contain duplicate or unbounded follow-up references,
  ratings may contain non-finite numbers, and the published payload limit counts
  strings but not JSON structure or numeric scalars. Define the implementation
  boundary and the tests required before shipping.
- **Instruction sources:** Historical whole-branch review plus a fresh run that
  explicitly loaded `adding-metadata-provider`; global and repository guidance
  remained available.
- **Classification:** Historical observed RED plus post-skill forward test.
- **Observed baseline:** Runtime once permitted unbounded season fan-out,
  non-finite numeric values, and payloads whose serialized bytes exceeded the
  stated bound; executable and serialized checks did not prove identical
  behavior. A fresh pre-edit control already identified these defects and was
  recorded as contaminated rather than relabeled RED.
- **Expected:** Bound every streamed response before decoding; enforce strict
  portable JSON, finite numbers, depth/node/count/text limits; validate and
  deduplicate all references before bounded fan-out; enforce aggregate budgets;
  and bind deterministic executable outcomes to serialized expectations.
- **Forbidden:** A byte limit that ignores structure/scalars, partial fan-out
  before validation, silent numeric coercion, provider-specific policy in core,
  or schema-only conformance evidence.
- **Post-skill evidence:** The explicit forward test placed read and JSON
  complexity limits in the provider transport, deduplication and aggregate
  budgets in provider orchestration, finite/range checks in normalization and SDK
  DTO construction, and semantic parity in executable-plus-serialized tests. It
  required boundary and boundary-plus-one cases, dishonest content lengths,
  duplicate references, aggregate exhaustion, redacted errors, and double close.
- **Causal limit:** The repository and historical findings exposed the same
  concerns. The forward run proves that the strengthened portable skill yields a
  complete implementation checklist; it does not isolate the skill as the only
  cause of that answer.

### Release-provider safety and lifecycle

- **Prompt:** A release provider has bounded search results, but validation and
  resolution endpoints can buffer large bodies, runtime and serialized snapshots
  use different URL/GUID rules, and the module installs process-global HTTP log
  filters. Decide the minimum correction under delivery pressure.
- **Instruction sources:** Historical whole-branch review; fresh control used
  `AGENTS.md`, canonical OpenSpec, repository code, and global pragmatic guidance
  while explicitly excluding `adding-release-provider`; forward test explicitly
  loaded the project skill.
- **Classification:** Historical observed RED, contaminated no-target-skill
  control, and post-skill forward test.
- **Observed baseline:** Runtime accepted snapshot values rejected by serialized
  conformance; some validation/POST paths were buffered without an effective cap;
  module construction mutated logging state it did not lifecycle-own. The fresh
  control already found these issues and is not counted as a new RED.
- **Expected:** Bound every validation/search/intermediate/final response before
  decode or buffering; apply one SDK-owned safe GUID/infohash/public-page corpus
  across runtime, schema, executable, serialized, and core checks; keep module
  logs safe and host-owned process logging reversible by identity.
- **Forbidden:** Module-owned global logger mutation, provider-specific core
  sanitizers, approximate parity, automatic retries without reconciliation, or a
  generic transport framework created for one provider.
- **Post-skill evidence:** The same prompt with the skill explicitly loaded put
  HTTP ownership in the module, global logging policy in the host lifespan, and
  opaque-token/persistence ownership in core. It required declared and streamed
  bounds on every endpoint, a shared adversarial parity corpus, real descendant
  logger tests, exact cleanup identity, and an OpenSpec stop before changing
  contract or ownership.
- **Causal limit:** Canonical specs and existing code already made many decisions
  discoverable. The comparison proves that the skill is complete and usable; it
  does not attribute the answer exclusively to that skill.

### Download-client acknowledgement ambiguity

- **Prompt:** A download client bounds some GET responses, but authentication,
  submission acknowledgements, and lookup can be arbitrarily large; the remote
  may accept a task before the POST times out. Define exact correlation,
  reconciliation, and response limits without adding a retry subsystem.
- **Instruction sources:** Historical acquisition review; fresh control used
  repository instructions, canonical specs, code, tests, and global pragmatic
  guidance while excluding `adding-download-client`; forward test explicitly
  loaded it.
- **Classification:** Historical observed RED, contaminated no-target-skill
  control, and post-skill forward test.
- **Observed baseline:** Some POST acknowledgement paths buffered bodies, exact
  lookup could select the first duplicate, and only one timeout code entered
  reconciliation even though other post-handoff failures could be ambiguous. The
  fresh control found these gaps and is recorded as already-correct evidence.
- **Expected:** Bound declared and streamed bytes plus collection counts for every
  authentication/destination/acknowledgement/lookup endpoint; submit the exact
  correlation once; locally prove equality; reconcile one exact match; and leave
  uncertain, malformed, oversized, duplicate, or visibility-limited lookup
  outcomes pending without automatic resubmission.
- **Forbidden:** Substring correlation, first-match wins, silent field coercion,
  automatic retry/polling, new task states or ledgers, or treating a post-handoff
  parse failure as a definitive remote rejection.
- **Post-skill evidence:** The explicit forward test applied per-endpoint boundary
  and boundary-plus-one tests, raw collection caps, strict parsing, exact and
  near-match cases, one-submit reconciliation, and executable/serialized parity.
  Crucially, it stopped for `openspec-update-change` because canonical behavior
  did not yet define all broader ambiguous outcomes.
- **Causal limit:** The prompt and repository already contained overlapping
  timeout/correlation guidance. The run proves the strengthened skill adds the
  complete endpoint and ambiguity checklist and respects authorization; it is not
  isolated proof of causation.

### Metadata schema rename and stored revisions

- **Prompt:** Rename or reshape a normalized provenance field described as
  internal while immutable stored revisions, current/pinned reads, APIs, naming,
  NFO, UI, and retention may consume it. No user or compatibility inventory has
  been performed.
- **Instruction sources:** Historical processor-wire review; fresh control used
  repository instructions, canonical specs, code, schemas, tests, and global API
  and pragmatic guidance while excluding `evolving-metadata-schema`; forward test
  explicitly loaded it.
- **Classification:** Historical observed RED, contaminated no-target-skill
  control, and post-skill forward test.
- **Observed baseline:** An internal rename once leaked into processor JSON and
  OpenAPI; persistence adapters concealed a different stored name; tests did not
  initially characterize the full wire. The fresh control correctly preserved
  v1 and traced consumers, so it is not labeled a forced RED.
- **Expected:** Inventory actual data and consumers; characterize DTO/schema,
  stored bytes, current and pinned reads, and API/OpenAPI before design; choose an
  explicit old-version read/project/migrate/reject policy; trace all producers,
  imports, overrides, projections, exports, and retention; version intentional
  incompatible semantics without rewriting history.
- **Forbidden:** Global rename, silent v1 redefinition, scattered aliases,
  cosmetic revision rewrites, compatibility based on assumption, or treating a
  product release number as a contract version.
- **Post-skill evidence:** With the skill loaded, the run rejected the “internal”
  premise, preserved the existing v1 field and single persistence-boundary
  translation, required immutable v1 current/pinned reads plus a version-aware
  new-write policy, and enumerated Manual/TMDB, validation, overrides, storage,
  control/processor, naming/NFO/UI, and retention tests. It stopped pending real
  deployment/consumer inventory and an approved OpenSpec decision.
- **Causal limit:** Existing repository code already embodied part of this
  policy, and inspection was intentionally bounded. The test proves the portable
  trace and authorization rules are usable, not exclusive causation.

### OpenSpec phase authorization under implementation pressure

- **Prompt:** No active change exists. A planning discussion described the
  intended proposal and the user then says `Start implementation`. Decide
  whether proposal artifacts may be created and applied in the same turn. A
  second compatibility fix is requested immediately after the first change.
- **Instruction sources:** Historical Copilot/DeepSeek session with `AGENTS.md`
  and the generated `openspec-propose` and `openspec-apply-change` skills read
  explicitly.
- **Classification:** Historical observed RED.
- **Observed baseline:** The agent quoted the planning/apply authorization
  boundary, then treated the implementation request as pre-approval for artifacts
  that did not exist. It chained proposal into apply, created the second change's
  artifacts without their current `openspec instructions`, selected `skip_specs`
  without review, edited a canonical spec directly, and archived both changes
  before a separate close request.
- **Expected:** Create and present proposal artifacts, then stop. Only a later
  user message can authorize apply. Apply reports implementation status and
  stops; verification and archive remain separate actions. Domain skills add
  constraints but never authorize lifecycle transitions.
- **Forbidden:** Pre-approval, proposal-to-apply or apply-to-archive chaining,
  direct canonical-spec edits during apply, self-approved workflow metadata, or
  direct CLI commands used to bypass lifecycle skill prompts.
- **Refinement:** `AGENTS.md` now states the temporal approval rule and terminal
  phases. `developing-media-finder-changes` repeats the apply entry and exit
  gates, `adding-download-client` states that it is not a lifecycle entry point,
  and `verifying-and-publishing-media-finder` verifies approved artifacts before
  publication claims.
- **Post-skill evidence:** Pending. This environment has no direct channel to the
  DeepSeek agent, and no independent agent run was authorized for this session.
  Structural validation and repository tests do not establish behavioral
  compliance.
- **Causal limit:** The historical run proves the failure despite overlapping
  correct instructions. The refinement closes its exact rationalizations, but a
  future explicit forward test is still required before claiming agent-level
  parity.

### Apply-complete handoff before OpenSpec closure

- **Prompt:** All implementation tasks and local gates for
  `enforce-complete-delivery-lifecycle` are complete late in the day. A teammate
  asks the agent to call the task complete, commit the dirty tree, and leave
  specification sync, archive, and GitHub publication to tomorrow. The current
  turn authorized apply only. Choose the actual status, actions, and next
  authorization without deferring the decision.
- **Instruction sources:** A fresh Luna subagent used current `AGENTS.md`, the
  active proposal, design, delta spec, tasks, and relevant repository memory. It
  was explicitly prohibited from reading `developing-media-finder-changes`; the
  shared checkout and repository completion invariant remained visible.
- **Classification:** Contaminated no-target-skill control.
- **Observed baseline:** The control already complied. It reported the apply
  phase complete and overall work incomplete, refused commit, sync, archive,
  push, or publication from the apply-only turn, and requested a later
  verification/archive authorization with canonical sync selected.
- **Expected:** Report `Implementation phase: complete` and `Overall work:
  incomplete`, preserve the terminal apply boundary, and identify the separate
  verification/archive authorization as the next required action.
- **Forbidden:** Calling the overall task complete, committing a candidate that
  omits applicable sync/archive, or chaining apply into archive or publication.
- **Post-skill evidence:** The same prompt with
  `developing-media-finder-changes` explicitly loaded produced the required
  `Implementation phase: complete` and `Overall work: incomplete` distinction,
  refused commit, sync, archive, and push in the apply turn, and requested a
  separate verification/archive authorization before the already mandated
  protected-branch delivery chain.
- **Causal limit:** The compliant control proves the new repository invariant is
  already sufficient in this environment. The forward run proves that the
  skill's local handoff contract is usable, but cannot establish that the skill
  alone causes compliance.

## Maintenance rule

When updating this document, retain raw decisions and limitations rather than
upgrading the strength of evidence. A post-skill run replaces `Pending` only
after the target `SKILL.md` was explicitly loaded and the actual outcome was
reviewed. Release-specific identifiers belong in release plans and notes, not in
the reusable skills catalog.
