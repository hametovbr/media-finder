## 1. Tests first

- [x] 1.1 Replace the assumed absence fixture with the output the registry tool was observed to print for a missing tag, and observe the classifier reject it today. Observed RED: `only authoritative manifest absence is treated as an absent registry tag` failed while the fixture asserted `ERROR: <reference>: not found`, the exact line `docker buildx imagetools inspect` prints for `ghcr.io/hametovbr/media-finder:v0.5.0`; the previous fixture asserted a `manifest unknown` message the tool does not produce.
- [x] 1.2 Add failing near-miss cases that must stay non-authoritative: `network not found` with a resolution code, an HTTP-shaped 404, an authentication failure and a timeout, each asserted alongside the accepted absence so the two directions cannot drift apart. The accepted form and the rejected forms are asserted by adjacent tests against the same client surface.
- [x] 1.3 Add a failing assertion that a blocked publication carries the command diagnostic in its failure record and in the written evidence. Observed RED: `an inspection failure records the command diagnostic that identifies its cause` failed because the failure record kept only the command and exit status.

## 2. Implement the minimum change

- [x] 2.1 Extend the absence classification in `scripts/release-publication.mjs` to accept the observed manifest-missing diagnostic while keeping every existing rejection of authorisation, network, timeout, TLS and proxy diagnostics. The observed form is anchored to the `ERROR: <reference>: not found` line shape, so the daemon's `HTTP 404 not found` and a `network not found` message are still not read as absence.
- [x] 2.2 Carry a bounded, sanitized command-diagnostic excerpt into the command failure record and into the reported failure, so the evidence writer and the workflow summary both state the cause. The excerpt is limited to 2000 characters, strips URL userinfo and control characters, and drops any line that looks credential-shaped.
- [x] 2.3 Remove the superseded assumption-based fixture in the same slice; the absence test now asserts the observed output and no remaining path matches only a message the tool never prints.

## 3. Verify

- [x] 3.1 `node --test scripts/release-publication.test.mjs`: 33 tests, 33 passed, 0 failed — the observed absence is accepted and every near-miss stays non-authoritative.
- [x] 3.2 Repository gates on this candidate, all passing: `node --test scripts/release-automation.test.mjs` 113 passed; `pnpm delivery:test` 155 passed; `pnpm delivery:validate`; `pnpm docs:check` 486 files; strict `pnpm spec:validate` 10 passed, 0 failed; `uv run ruff format --check .` 329 files; `uv run ruff check .` clean.
- [x] 3.3 Complete and coherent: no workflow, controller, delivery-policy or application file changed, and the already published `v0.5.0` GitHub Release identity is untouched — the image is published by re-running the same guarded publisher.
