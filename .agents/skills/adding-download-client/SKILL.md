---
name: adding-download-client
description: Use when adding, replacing, or changing a Media Finder download-client module, its destinations, artifact submission, correlation, manifest, fixtures, or conformance.
---

# Adding a Download Client

Build a static submission adapter. Core owns acquisition records, idempotency,
state transitions, and the `mf-acq-<uuid>` correlation value.

1. Start with the approved OpenSpec delta and a deterministic RED test. Update
   it for changes to artifacts, destinations, configuration, correlation, or
   public behavior.
2. Add `packages/modules/download-<name>/` as one independent wheel. Its public
   `registration()` returns `DownloadClientRegistration` and imports only
   `media_finder_sdk` plus implementation libraries. Add its workspace entry,
   direct host dependency in `apps/server/pyproject.toml`, lockfile,
   `Dockerfile` wheel assembly, and deterministic package/delivery inventories
   in the same change.
3. Declare `download-client` identity, compatibility, capabilities
   (`destinations`, `submit`, `correlation`, and `magnet` and/or `torrent`),
   translations, and exact value-free environment declarations in
   `src/<package>/module.toml`. Use `ResolvedModuleEnvironment`; never read
   `os.environ`, persist environment references, create UI/configuration forms,
   or reveal credentials, artifact bodies, download URLs, or passkeys.
4. List live destinations immediately before submission, accept the exact
   correlation unchanged, submit only declared in-memory artifact forms, and
   implement exact `find_by_correlation`. Do not poll progress, retry ambiguous
   timeouts, create media states, or receive persistence/UI/core objects.
5. Test real deterministic fixtures through
   `assert_download_registration_conforms`: required-variable failures, each
   declared artifact kind, destinations, exact correlation, lookup, safe errors,
   redaction, limits, and idempotent double close.
6. Add `fixtures/conformance.json` bound to the raw `module.toml` hash and
   validated by `schemas/module-sdk/v1/conformance.schema.json`. Serialize only
   safe descriptors; keep magnets and torrent bytes in executable fixtures.
7. Register it explicitly in
   `apps/server/src/media_finder_server/modules.py`. If it becomes selected,
   update that explicit host selection in the same review—registration order
   must not choose it. Run focused tests, `pnpm module-conformance:test`,
   `pnpm module-conformance:validate`,
   `uv run pytest tests/architecture/test_package_boundaries.py tests/test_wheel_isolation.py`,
   format, lint, type, and `pnpm spec:validate`.

Do not add a plugin loader, module-owned database state, progress monitoring,
or a serialized fixture that is not paired with executable conformance.
