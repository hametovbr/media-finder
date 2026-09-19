## Why

A stable publication cannot start while a moving tag points at an image whose version label the publisher refuses to read. The repository's own `latest` and `0.4` tags point at the v0.4.0 image, whose `org.opencontainers.image.version` label is `v0.4.0`, and the publisher parses that value strictly as `X.Y.Z`. The moving tag is therefore reported as `moving_tag_conflict: Moving tag ghcr.io/hametovbr/media-finder:latest has unverifiable image metadata.` in run `35469590624`, before any build, so the repair of the v0.5.0 image and every later stable release stop for as long as `latest` points at a pre-existing image.

## What Changes

- Reading an existing moving tag's version label accepts the conventions this project has actually published — both `vX.Y.Z` and `X.Y.Z` — while the value used for ordering and conflict decisions stays the parsed canonical version.
- The canonical bare form remains the only form the publisher writes into new images; nothing about what is published changes.
- Tolerance is limited to reading the label: an unreadable or absent version label still refuses, unknown or conflicting shapes still refuse, and a regression to a newer moving tag still refuses.
- A fixture reproduces the historical `v0.4.0` label on a moving tag and the reconciliation that follows, alongside the existing rejection cases.

## Capabilities

### Modified Capabilities

- `deployment-and-delivery`: reading an existing moving tag's version label must interpret the label conventions this project has published, including a leading `v`, so that reconciliation with an earlier release remains possible, without relaxing ordering, immutability or conflict decisions.

## Impact

- `scripts/release-publication.mjs` and `scripts/release-publication.test.mjs`.
- No change to the workflow, its permissions, the publication commands or the published image contents.
- Unblocks the pending v0.5.0 image completion and any stable publication performed while `latest` points at an image built before this fix.
