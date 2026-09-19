## Context

See proposal.md for the three runtime defects and their evidence. The delivered
workflow gates the manual job on `github.event_name == 'workflow_dispatch'` but
leaves the release-event job gated only on `github.event.release.prerelease ==
false`, which GitHub's loose equality evaluates as true when the field is absent.
The publisher reads its event revision from `process.env.GITHUB_SHA`, and GitHub
documents that the `GITHUB_*` default variables cannot be overwritten by a
workflow, so the delivered `env:` block was inert. The publisher's build command
carries `--cache-from type=gha --cache-to type=gha,mode=max` from a plain `run:`
step, while neither release job exposes the Actions cache runtime environment.

An independent audit of the delivered revision added a fourth problem that is not
in the workflow: the delivery validator currently **requires** both known-bad
constructs — the unguarded release-event condition and the ineffective `env:`
override — so correcting the workflow alone would fail the repository's own
publication gate. The same audit found the manual entry point's assertions too
weak to enforce the contract they describe, and confirmed several suspicions were
unfounded.

## Goals / Non-Goals

**Goals:** make each entry point act only for its own event, make the manual entry
point publish the revision it resolved, make building independent of environment
the publishing step does not supply, and make the delivery policy enforce the real
contract rather than the current shapes.

**Non-Goals:** adding Actions or registry permissions the jobs do not need,
changing the publisher's tag rules, the immutable-state guard, the resolution
rules, the verification contexts or the concurrency group, and enabling any cache
backend elsewhere.

## Decisions

### 1. Gate every entry point on its event explicitly

Both publication jobs test `github.event_name` before any event-specific field, so
a guard cannot become true merely because a field is missing for another event. The
manual job already did this; the release-event job did not, which is the asymmetry
that let it run on a dispatch. The validator assertion that currently requires the
unguarded expression is replaced in the same slice.

*Alternative considered:* keep the field-only condition and rely on the release
payload always being present. That is the assumption that failed, and GitHub's
coercion makes the failure silent rather than loud.

### 2. Replace the reserved variable at process level

The revision override moves into the command the step runs —
`env GITHUB_SHA="${{ steps.resolve.outputs.revision }}" node ...` — because a
workflow-level or step-level `env:` block cannot replace a `GITHUB_*` default. The
audit inventoried every variable the publisher reads and confirmed the revision is
the only value that differs between the two events; the rest are correct for a
dispatch. The validator assertion that currently requires the `env:` entry is
replaced by one that requires the command-level assignment.

### 3. Build without a cache backend the step cannot configure

The publisher's `docker buildx build` drops `--cache-from` and `--cache-to`. The
Actions cache backend needs runtime cache environment that a raw `docker buildx`
step does not receive, so any publication that has to build rather than reuse an
existing manifest would fail. Caching is an optimization, and the repository's
verification image job and edge publish job build with no cache backend at all, so
removing it makes the publisher consistent with the rest of the pipeline. A
publisher test asserts the build command carries no Actions cache backend.

*Alternative considered:* expose the Actions cache runtime variables to the step.
That depends on platform internals outside the documented workflow contract, and the
repository's other builds show the dependency is avoidable.

### 4. Bind the release commit's verification to the Actions application

The resolution step requires seven successful checks on the release commit by name.
Names alone are not provenance: another application can publish a check run with a
matching name. The query therefore also requires the GitHub Actions application, the
same discipline the release controller already applies to its own required
contexts.

### 5. The validator enforces the contract, not the prose

The manual entry point's assertions are strengthened to the real contract: the
resolution step's identity, inputs, refusals, version equality and seven
application-bound checks; both checkouts' revisions, history, credential posture,
paths and order; the staging step that copies the publisher out and removes the
trusted checkout; the exact trusted publication command rather than a substring that
`echo` would satisfy; the release URL; and the evidence upload's attempt-unique
name, retention, failure conditions and order. Each enforced property has a mutation test
that changes it — removing a guard or its refusal exit, replacing a refusal
diagnostic, or altering a path, a credential posture, an order, a command or an
artifact name — and the validator reports that change, so text that only describes
the contract does not satisfy it. The validator comment records that shape assertions cannot evaluate
GitHub's expression coercion, which is why the event gate is pinned explicitly.

Substring search cannot distinguish an enforced command from a described one, so
the assertions read the step after shell comments are stripped — tracking quote
state, because `${RELEASE_TAG#v}` contains a `#` inside double quotes — and require an
`exit` after every refusal guard. Because neither measure proves the step actually
stops, the resolution step is also executed with controlled `gh` and `git`
responses: each refusal must end the step with no revision written to
`GITHUB_OUTPUT`, while the exits are rewritten to show that static text cannot substitute for
running the step. Static exit detection is a heuristic backstop rather than a shell
interpreter: a here-document, a line continuation or a command substitution can
carry `exit 1` as inert text, so refusal behaviour is evidenced by execution, not by
the assertion that the text is present. A comment introducer is recognised after any shell separator, because
bash starts one at every word: `true;# cp ...` satisfies a search for the copy while
copying nothing, so the staging step is additionally compared as a complete command
list and executed, and the resolver harness answers each of the seven required
contexts individually so a dropped context cannot hide behind a uniform refusal.

## Risks / Trade-offs

- Without the cache, a full multi-architecture build is slower → publication is
  serialized by its concurrency group and infrequent, and the correctness of the
  published digest matters more than build time.
- Asserting exact expressions and commands is brittle to formatting → the existing
  `normalizedExpression` helper normalises whitespace, and commands are compared as
  exact strings because that is the property being enforced.
- The manual job's `check-runs` query relies on public-repository read access → the
  repository is public, and the audit could not confirm a token-permission failure
  there; the dependency is recorded rather than satisfied with an unused
  `checks: read` grant.
- The audit's remaining suspicions were checked rather than left silent: every other
  workflow condition behaves correctly for the events that can reach it
  (`ci.yaml` push-on-main, `prepare-release.yaml` and the manual job
  dispatch-on-main, the verification job's dispatch-or-stable-release disjunction,
  and the `always()`-guarded evidence uploads); the publisher reads only
  runner-provided variables besides the intentional revision and release inputs; and
  the two-checkout arrangement was reproduced locally with two revisions, where the
  release checkout's `HEAD` stayed on the resolved revision, the trusted publisher
  was staged outside the workspace, the `trusted` directory was absent afterwards,
  and the worktree stayed clean. `needs: verification` legitimately verifies the
  trusted publisher revision while the resolution step verifies the published
  source.

## Verification evidence

- The ineffective `env:` override is not merely a documented rule: in run
  `35467108954` the manual job failed with `checkout_revision_mismatch`, which the
  publisher raises by comparing `GITHUB_SHA` against the checked-out `HEAD`. The
  checkout was the resolved release revision and the tag-target comparison passes,
  so the failing comparison proves the publisher read the dispatch revision. The
  process-level form was confirmed locally to replace the variable for the child.
- No workflow declares a `GITHUB_*` variable in an `env:` block, and no workflow
  requests an Actions cache backend.
