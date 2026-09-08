## Context

See proposal.md and the delta spec. Existing `ci.yaml` invokes reusable verification on pull_request and main push. The browser job installs locked Playwright Chromium and runs `pnpm ui:browser`; it does not upload reports. Delivery validation requires exactly seven jobs and immutable action SHAs. Read-only Terra investigation confirmed this minimal extension point and the pre-archive lifecycle ambiguity.

The existing ui-feedback-recovery dirty implementation is a dependency of recovery-specific captures; preserve its recorded 22-path diff. This change owns evidence configuration and process clarity, not additional product fixes.

## Goals / Non-Goals

Goals: downloadable deterministic evidence, truthful tested-candidate provenance, and a usable preliminary hosted verification path that cannot be mistaken for final delivery.

Non-goals: a preview server, deployment, new required job, browser substitution, visual snapshot-baseline platform, custom CI runner, real integration fixtures, auto-merge, or reduced acceptance criteria.

## Decisions

1. Extend only the existing browser job. Keep locked install and `pnpm ui:browser`, all job names and contents:read permissions. Add a SHA-pinned official artifact-upload action; resolve its supported immutable SHA from the official repository during apply, not from memory. Upload declared report/output directories with seven-day retention after success or failure. Never use continue-on-error on the browser command. Fail on missing required evidence; setup/cancellation may yield only partial or no artifacts and remain blocked.

2. Use Playwright's existing reporters and attachments. Retain a readable HTML report with auto-open disabled and its test-result attachments. Do not enable trace, video, storage-state export or raw HTTP logging. Use one dedicated browser-evidence output root and a small provenance JSON produced with built-in Node APIs/environment values; do not introduce a custom reporter/parser service. Record actual `git rev-parse HEAD` separately from event SHA and PR head/base, run/attempt and package/browser versions. A PR merge checkout is integration evidence for that recorded head/base pair, not execution of head alone. Final required checks must still belong to the current head.

3. Capture a bounded 36-image matrix: the seven named failure/empty states plus metadata search pending and successful keyboard recovery, at en/ru x 360x800/1280x800. Use existing typed safe fixtures and route interception; intercept poster requests locally and reject unexpected external traffic in capture cases. Use stable scenario names, not query strings, for attachment names. Hold pending requests with explicit deferred fixtures, await rendered states/fonts/images, disable animations for capture only and settle requests before test teardown. Assert long-unbroken-query overflow and keyboard focus in the real browser. No golden-image comparison or animation changes to production UI.

4. Add structural enforcement to the existing delivery validator and mutation tests: missing upload, mutable action pin, missing failure-path publication, broadened permission, incorrect output/retention or masked browser failures must fail validation. Consume its existing parsed YAML; no auxiliary workflow language parser. Fixture browser assertions, not source-spelling tests, verify capture states.

5. Make preliminary verification an explicit separate phase. Current instructions prohibit final delivery before archive and prohibit publication in apply turns. Update the two canonical workflow requirements via the approved delta, clarify the narrow exception in AGENTS/docs, and adapt only the manually maintained publication skill. Run its required before/after pressure scenario without claiming an isolated control. Planning and apply remain terminal turns. A later user request may authorize a clean committed checkpoint, including both active changes and the current UI implementation, on a non-main branch with a draft PR to collect evidence. Label it non-final; never merge or publish an image. After evidence review, request separate archive, synchronize/archive both completed changes, shape the final candidate, and rerun all final-head checks/review before merge. Preliminary evidence may complete implementation-verification tasks for its exact candidate; it never supplies final delivery closure.

## Risks / Trade-offs

- A checkpoint commit is durable but non-final -> include active changes and unresolved gates in the draft PR and persistent roadmap; no false completion or premature merge.
- Checkout and PR head differ -> record both plus base; invalidate acceptance when either changes. Do not silently replace the existing merge-checkout CI behavior.
- Screenshots alone miss contrast and interaction -> inspect downloaded PNGs and report, record measured/observed contrast and targets separately; 118 local tests remain baseline-only evidence for their original diff.
- Artifacts expire or setup fails -> record blocked, preserve run/attempt references and rerun only through an authorized path. No public preview or production credentials are needed.
- CI cannot run until a checkpoint is published -> finish apply in one turn, use a subsequent explicitly authorized verification turn for the draft checkpoint; do not mark remote validation complete during offline apply.

## Migration Plan

No application or data migration. Apply the approved evidence and guidance changes, run local proportional validation and stop at handoff. On a subsequent verification request, preserve the local UI diff, publish a clean non-final checkpoint through available GitHub tools, create a draft PR, and inspect its exact run. Download and open artifacts before marking browser/visual tasks complete. Failure findings remain in their owning approved change; expanded product scope requires its own update.

After separately authorized synchronization/archive, final delivery follows existing protected-branch checks. Rollback is a normal revert of evidence configuration and guidance; no runtime migration. No new service or package is introduced.
