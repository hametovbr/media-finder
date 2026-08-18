---
name: debugging-media-finder-failures
description: Use when Media Finder tests, CI, packaging, migrations, browser checks, image checks, or runtime behavior fail or disagree across machines, commits, or environments.
---

# Debugging Media Finder Failures

Establish the first failing boundary and its owner before changing code. Do not
turn missing evidence into a product fix or weaken a gate to make it green.

## Capture the state

Record the exact command, output, exit code, full HEAD, worktree status, platform,
tool versions, environment differences, and relevant workflow/run SHA. Evidence
from another commit or a dirty tree describes a different candidate.

Reproduce the smallest real boundary without changing it. Read the full error and
trace inputs backward until the first unexpected value, path, state, or response.

## Classify before fixing

- **Code defect:** the failure reproduces in the supported locked environment and
  violates an approved behavior or contract.
- **Environment limitation:** a required external capability is unavailable, such
  as network, registry, browser, Docker, credentials, permissions, or disk. Report
  `not run` or `blocked`; do not call it passed.
- **Stale worktree/environment:** generated artifacts, editable installs, caches,
  uncommitted files, or an unsynchronized environment make the run differ from
  clean HEAD. Reproduce cleanly before editing production.
- **Evidence mismatch:** logs or checks belong to another SHA, ref, image digest,
  platform, or workflow revision. Discard them for the current claim.

## Diagnose and repair

1. Form one root-cause hypothesis and run the narrowest observation that can
   disprove it.
2. Discover tools through `PATH` first. Use an OS-aware repository fallback only
   when the project owns it. Never embed one workstation's executable path.
3. For CI failures, inspect the actual failing job, step, command, environment,
   and commit. Reproduce its boundary locally when possible.
4. Add a focused RED for a code defect, implement the minimum fix, and rerun the
   original failure. For an environment limitation, fix setup or document the
   missing evidence instead of changing product semantics.
5. Run adjacent regressions and confirm the original root cause—not a skipped
   path—made the result green.

## Do not

- skip a failing suite, relax a validator, or catch a broad exception merely to
  obtain green CI;
- install undeclared dependencies into a shared environment and treat that state
  as reproducible;
- confuse network denial during a wheel build with a package defect;
- claim Linux, browser, image, or release verification from a platform where it
  did not run;
- fix a downstream symptom before proving the upstream cause.

## Handoff

Report classification, reproduced command, root cause, minimal change, exact
GREEN evidence, discarded stale evidence, unavailable checks, and current
HEAD/worktree state.
