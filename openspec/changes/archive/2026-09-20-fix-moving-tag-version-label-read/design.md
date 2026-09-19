## Context

See proposal.md for the failure and its evidence. The publisher reads an existing tag through `docker buildx imagetools inspect`, derives a per-platform entry from the image config labels, and parses the raw `org.opencontainers.image.version` value with `parseStableVersion()`, whose pattern accepts only a bare `X.Y.Z`. The same parser also validates the release tag, the `VERSION` file, the requested version and the immutable tag's labels, where a leading `v` must keep being rejected.

## Goals / Non-Goals

**Goals:** read the version label of an image this project published earlier, whatever prefix convention it used, so that a moving tag can be reconciled with an earlier release; keep every ordering, immutability and conflict decision based on the interpreted version.

**Non-Goals:** accepting arbitrary label spellings (build metadata, prereleases, whitespace, other prefixes), changing what the publisher writes into new images, or changing the immutable-tag verification path.

## Decisions

### 1. Tolerate the published prefix only when reading an existing image's label

A dedicated read strips a single leading `v` before parsing and is used only when interpreting an existing moving tag.

*Alternatives considered:* widening the shared version pattern — rejected, because the same parser guards the release tag, the `VERSION` file and the requested version, where a `v` prefix must still be refused; special-casing the `latest` tag name — rejected, because the convention belongs to the label rather than the tag, and the `0.4` tag carries the same legacy label.

### 2. Keep the canonical form for everything written

Builds continue to set the bare `X.Y.Z` label, so images published after this change are read by the strict path. The tolerance exists to interpret history, not to legitimise it.

### 3. Prove the tolerance with the historical label and keep every refusal

A test constructs a moving tag whose existing image carries `v0.4.0` and asserts that reconciliation proceeds instead of refusing. The refusal cases remain asserted: an unparseable label, an absent label and a moving tag that points at a newer release.

## Risks / Trade-offs

- A tolerance could mask a genuinely malformed label → only one leading `v` is accepted; any other deviation still throws, and the refusal path stays asserted.
- The immutable-tag verification compares the raw label with the requested version → unchanged, so an image whose label carries `v` is still refused as the immutable release, which is the fail-closed behaviour this change preserves.
- The tolerance could be removed later without anyone noticing that publication is blocked again → the historical fixture keeps the exact live label in the suite.
