## 1. Tests first

- [x] 1.1 Add a failing publisher test in which a moving tag already points at an earlier release whose version label carries the published `v` prefix, and publication must reconcile instead of stopping with `moving_tag_conflict`.
- [x] 1.2 Add failing cases proving the tolerance is limited to that read: an unparseable label, an absent label, a label with build metadata, and a moving tag that points at a newer release each still refuse.
- [x] 1.3 Observe the reconciliation, prefixed-regression and prefixed-immutable cases fail against the delivered revision, confirm the malformed-label refusals hold there as well, and reproduce the live label from run `35469590624` so the fixture matches the registry rather than an assumption.

## 2. Implement the minimum change

- [x] 2.1 Read an existing image's version label tolerantly, accepting exactly one leading `v`, and use that read only when interpreting a moving tag.
- [x] 2.2 Leave the shared strict version parser, the canonical label written by builds and the immutable-tag verification unchanged.

## 3. Verify

- [x] 3.1 Run `node --test scripts/release-publication.test.mjs`, `node --test scripts/validate-delivery.test.mjs`, `node scripts/validate-delivery.mjs`, `node --test scripts/release-automation.test.mjs` and `pnpm delivery:test`.
- [x] 3.2 Run `pnpm docs:check` and strict `pnpm spec:validate`.
- [x] 3.3 Confirm against the registry that the delivered revision refuses the live `latest` label and that the fixed revision reconciles the same label, so the fixture is tied to the observed registry state.
- [ ] 3.4 After delivery, re-run the manual entry point for `v0.5.0` and verify the published tags, digest, both architectures and source revision. Pending: it follows the merge of this change, which has not happened yet.

## Evidence

- Registry state used by the fixture: `docker buildx imagetools inspect` on
  `ghcr.io/hametovbr/media-finder:latest` reports
  `org.opencontainers.image.version = v0.4.0` on both architectures, and run
  `35469590624` failed with `moving_tag_conflict: Moving tag
  ghcr.io/hametovbr/media-finder:latest has unverifiable image metadata.`
- RED against the delivered revision, with the implementation reverted to
  `origin/main`, measured on the final suite: 43 tests, 40 passed, 3 failed. The
  failures are reconciliation, the v-prefixed regression (which refused with
  `moving_tag_conflict` instead of `moving_tag_regression`) and the prefixed
  immutable stand-in (which refused with the wrong code). The five malformed-label
  refusals pass before and after the change, which is what shows the tolerance is
  limited to the published prefix.
  `parseStableVersion("v0.4.0")` throws `invalid_version`, and the same value with
  the prefix removed parses to `0.4.0`.
- The four refusal cases pass before and after the change, so the tolerance is
  limited to the published prefix; the v-prefixed newer moving tag still refuses
  with `moving_tag_regression`.
- Mutation checks, each run against the 43-test suite with one source edit and the
  module restored afterwards:
  - tolerance removed (`const text = value`) -> 40 passed, 3 failed: reconciliation,
    the v-prefixed regression and the prefixed immutable stand-in.
  - strip every leading `v` (`value.replace(/^v+/, "")`) -> 42 passed, 1 failed: the
    repeated-prefix refusal.
  - strip any non-digit prefix (`value.replace(/^[^0-9]+/, "")`) -> 41 passed, 2
    failed: the repeated-prefix and unexpected-prefix refusals.
  - tolerated read applied to the immutable comparison
    (`parsePublishedVersionLabel(platform.version).text !== expectedVersion`) -> 42
    passed, 1 failed: the prefixed immutable stand-in, and no other test.
  Each promise in this change is therefore load-bearing, and the counts above are the
  numbers actually observed rather than inferred.
- GREEN after the change: `release-publication.test.mjs` 43/43 (was 35),
  `validate-delivery.test.mjs` 173/173, `validate-delivery.mjs` exit 0,
  `release-automation.test.mjs` 113/113, `pnpm delivery:test` 195/195,
  `pnpm docs:check` 502 files, strict `pnpm spec:validate` 9/9 (10/10 while this
  change was still active, before archiving).
