## Context

See proposal.md for the failure and its evidence. The publisher treats an
immutable tag that does not exist yet as a normal first-publication state, and it
must decide that from the registry tool's own output. The observed output for a
missing tag, captured against `ghcr.io/hametovbr/media-finder` while diagnosing
release `v0.5.0`, is:

```console
$ docker buildx imagetools inspect ghcr.io/hametovbr/media-finder:v0.5.0
ERROR: ghcr.io/hametovbr/media-finder:v0.5.0: not found
```

The same tool inspects an existing tag successfully, so the registry, the login and
the network path were all working. The existing fixtures instead assert
`Error response from daemon: manifest unknown: manifest unknown`, which the tool
does not produce.

## Goals / Non-Goals

**Goals:** establish absence from the tool's real output, keep refusing to read
transient or authorisation failures as absence, and make a blocked publication
explain itself.

**Non-Goals:** changing the controller's token-issuance diagnostics, changing the
release workflow, changing how moving or immutable tags are chosen, and rebuilding
or overwriting anything already published.

## Decisions

### 1. Recognise the diagnostic the tool actually emits

The classifier keeps its existing guard rails — a real non-zero process exit, no
signal termination, no HTTP-shaped 404 — and additionally accepts the observed
manifest-missing form, while every authentication, authorisation, network,
timeout, TLS and proxy diagnostic continues to make the error non-authoritative.

*Alternative considered:* treat any non-zero inspection result as absence. That
would let a registry outage or a credential problem silently pass as "not yet
published" and push the run toward building and publishing over an unknown state.
It is rejected.

### 2. Fixtures encode observed output, not assumed output

The absence and non-absence fixtures are written from the strings the tool was
observed to print, including the missing-tag line above and the near-miss forms
that must stay non-authoritative (`network not found`, an HTTP-shaped 404, an
authentication failure, a timeout). A fixture that asserts a plausible-looking
message the tool never prints is treated as a defect in the fixture.

### 3. A blocked publication records its diagnostic

The command failure record gains a bounded, sanitized excerpt of the command's
diagnostic output, which the evidence writer and the workflow summary already
carry. Bounding and sanitizing reuse the existing evidence rules so no credential
or authenticated URL can enter a published artifact. The registry command line
never contains a credential: login is performed by the workflow and the tool reads
it from the Docker configuration.

## Risks / Trade-offs

- Broadening acceptance could mistake an outage for absence → the explicit
  rejection list and the requirement for a recognised manifest-missing phrase keep
  that path closed, and both directions are covered by fixtures.
- Recording command output could leak sensitive text → the excerpt is bounded and
  passes the existing sanitizer before it is written anywhere.
