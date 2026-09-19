## Why

The first stable publication under the new publisher was blocked at its very first
registry inspection. `docker buildx imagetools inspect ghcr.io/hametovbr/media-finder:v0.5.0`
prints `ERROR: ghcr.io/hametovbr/media-finder:v0.5.0: not found` for a tag that does
not exist yet, but the absence classifier accepts only `manifest unknown`,
`name unknown` or `no such manifest`. A legitimately absent immutable tag at first
publication is therefore reported as a registry failure, and release `v0.5.0` is
published with no container image.

The publisher's 32 tests did not catch this because their absence fixtures assert
`Error response from daemon: manifest unknown: manifest unknown`, a message the CLI
does not produce. The fixtures encoded an assumption about the tool instead of its
observed output. A second defect made the failure hard to diagnose: the command
failure record keeps only the command and exit status and discards the CLI
diagnostic, so neither the workflow log nor the evidence artifact states why the
inspection failed.

## What Changes

- Establish manifest absence from the diagnostic the registry CLI actually emits,
  while still refusing to read authentication, authorisation, network, timeout or
  TLS diagnostics as absence.
- Build the absence fixtures from observed CLI output rather than an assumed
  message, and cover the exact forms the tool produces for a missing tag and for
  the failure modes that must not be mistaken for absence.
- Carry the safe CLI diagnostic into the failure record so a blocked publication is
  explainable from the workflow log and the evidence artifact alone.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-and-delivery`: the stable publication requirement gains an explicit
  contract for how registry absence is established and what a blocked publication
  must report.

## Impact

Affected owners: `scripts/release-publication.mjs` and
`scripts/release-publication.test.mjs`. No controller, workflow, delivery-policy or
application file changes, and no state migration: the already published `v0.5.0`
GitHub Release keeps its identity and its image is published by re-running the same
guarded publisher after the fix. The controller-side analogue — a provider response
body dropped from an issuance failure — is recorded here as a known related gap but
is deliberately not changed by this proposal.
