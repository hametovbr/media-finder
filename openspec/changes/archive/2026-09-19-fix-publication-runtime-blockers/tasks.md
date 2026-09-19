## 1. Tests first

- [x] 1.1 Add a failing delivery-policy test that removes the event gate from the release-event publication condition and expects a reported failure naming the missing event guard.
- [x] 1.2 Add a failing delivery-policy test that moves the resolved-revision override back into the step's `env:` block and expects a reported failure naming the command-level requirement.
- [x] 1.3 Add a failing publisher test that asserts the build command carries no Actions cache backend, so the dependency on runtime cache environment cannot return unnoticed.
- [x] 1.4 Add failing delivery-policy tests for the manual entry point's real contract rather than its prose: the resolution step must keep its `resolve` identity, its token and tag inputs, its canonical-tag and stable-release refusals, its version-equality check and its seven context checks bound to the GitHub Actions application; the checkouts must keep the release revision with complete history and the trusted revision without persisted credentials at their exact paths and order; the staging step must copy the publisher out and remove the trusted checkout; the publication command must be the exact trusted invocation rather than a substring that `echo` would satisfy; the evidence upload must keep its attempt-unique name, retention, failure conditions and order; a commented-out command must not satisfy an executable assertion; and every refusal guard must be shown to stop the step rather than merely appear in it.
- [x] 1.5 Observe every new test fail against the delivered revision, so the guards reject the exact conditions that reached or would have reached a live run.

## 2. Implement the minimum change

- [x] 2.1 Gate the release-event publication job on `github.event_name == 'release'` in addition to rejecting prereleases, and replace the validator assertion that currently requires the unguarded condition.
- [x] 2.2 Move the resolved-revision override into the manual job's command so it replaces the reserved `GITHUB_SHA` for the publisher process, and replace the validator assertion that currently requires the ineffective `env:` entry.
- [x] 2.3 Remove `--cache-from` and `--cache-to` from the publisher's `docker buildx build` invocation, leaving the build otherwise unchanged.
- [x] 2.4 Bind the resolution step's verification check to the GitHub Actions application, so a same-named check run from another application cannot satisfy the release commit's verification requirement.
- [x] 2.5 Strengthen the manual entry point's validator assertions to the contract described in 1.4, including the exact publication command, the evidence-upload contract, comment-stripped executable text for every command and refusal, and the publication order.
- [x] 2.6 Record in the validator why shape assertions alone cannot evaluate GitHub's expression coercion, so the event gate is pinned deliberately rather than incidentally.

## 3. Verify

- [x] 3.1 Run `node --test scripts/validate-delivery.test.mjs`, `node scripts/validate-delivery.mjs` and `node --test scripts/release-publication.test.mjs`; confirm the delivered shape passes and every mutation case is rejected.
- [x] 3.2 Run `node --test scripts/release-automation.test.mjs`, `pnpm delivery:test`, `pnpm docs:check` and strict `pnpm spec:validate`.
- [x] 3.3 Confirm `env GITHUB_SHA=<revision> node <script>` actually replaces the variable for the child process while a workflow `env:` block cannot, and confirm no image build in this repository relies on the Actions cache backend.
- [x] 3.4 Record the audit's unfounded suspicions as explicitly checked rather than silent: every other workflow condition behaves correctly for its events, the publisher reads no other event-specific variable, and the two-checkout arrangement leaves no residual file and does not disturb the release checkout's `HEAD`.
- [x] 3.5 Execute the real resolution step with controlled `gh` and `git` responses and assert that each of the seven contexts, and each other refusal, stops the step with no revision output and its own diagnostic. Mutating the exits shows only that static text cannot substitute for execution: the static exit check is a heuristic that a here-document, line continuation or command substitution can satisfy with inert text, and the executed refusal cases are the evidence.

## Evidence

- Independent review round (`codex/gpt-6-astra`) on head `8b25146` returned
  `needs_revision` with two validator findings, both since closed: the checkout,
  staging and ordering guards were not enforced (a shallow release checkout, a
  renamed trusted path with persisted credentials, a commented staging command and
  staging moved before the checkouts all passed), and the refusal guards were
  matched as text without the exit that makes them refuse. The validator now strips
  shell comments before matching executable text, pins the release checkout's
  history, the trusted path and credential posture, the full publication order and
  the release URL, requires an exit after every refusal guard, and runs the real
  resolution step with stubbed `gh`/`git` for each refusal. Each new guard has an
  individual mutation test. A second review round on head `82b01d0` closed two
  further bypasses with the same evidence discipline: `true;# cp ...` (bash starts a
  comment after any separator, so the copy never ran while the text remained) and
  dropping ` image` from the resolved context loop, which no uniform stub could
  expose. The staging step is now compared as a whole command list and executed for
  real, and the resolver harness answers each of the seven contexts individually.
  A third review round on head `5aab6c3` found one vacuous negative control (a
  uniform `STUB_CHECK` fallback that the per-context branch now shadows, so the
  control fixture was valid either way) and confirmed three static-parser
  limitations. The control now uses a per-context failure and asserts that the
  unmodified step refuses the same fixture, and the limitations are recorded rather
  than papered over with a larger shell parser.

- RED before implementation: 8 new delivery-policy tests failed on the delivered
  revision (`node --test scripts/validate-delivery.test.mjs`), including the case
  that reproduces the shipped shape verbatim, and the publisher build assertion
  failed on the two `--cache-*` arguments.
- GREEN after implementation: `validate-delivery.test.mjs` 146/146 (was 138),
  `release-publication.test.mjs` 35/35, `release-automation.test.mjs` 113/113,
  `pnpm delivery:test` 168/168 (was 160), `node scripts/validate-delivery.mjs` exit
  0, `pnpm docs:check` 497 files, strict `pnpm spec:validate` 10/10.
- Process-level override: `GITHUB_SHA=<sha> node -e ...` printed the supplied SHA;
  the live run `35467108954` proves the `env:` form does not reach the publisher,
  because the failure was the `GITHUB_SHA`-versus-`HEAD` comparison while the
  checkout was the resolved release revision.
- Two-checkout arrangement reproduced with two revisions: release `HEAD` unchanged,
  trusted publisher staged outside the workspace, `trusted` absent afterwards,
  worktree clean. No workflow declares a `GITHUB_*` variable and none requests an
  Actions cache backend.
