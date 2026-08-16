---
name: adding-release-provider
description: Use when adding, replacing, or changing a Media Finder release-provider module, its torrent search, artifact resolution, manifest, safe release snapshots, fixtures, or conformance.
---

# Adding a Release Provider

Add one trusted static release module behind the specialized SDK contract. Core
owns opaque browser selections, acquisition persistence, and artifact lifetime.

1. Start with the applicable approved OpenSpec delta and a deterministic RED
   test. Update the delta for changed release search, artifacts, safe snapshots,
   configuration, or public errors.
2. Add `packages/modules/release-<name>/` as an independent wheel. Expose only
   `registration()` returning `ReleaseProviderRegistration`; depend only on
   `media_finder_sdk` and implementation libraries. Add its workspace entry,
   direct host dependency in `apps/server/pyproject.toml`, lockfile,
   `Dockerfile` wheel assembly, and deterministic package/delivery inventories
   in the same change.
3. Put `release-provider` identity, compatibility, `search`/`resolve`, at least
   one of `magnet` or `torrent`, translations, attribution, and exact value-free
   environment declarations in `src/<package>/module.toml`. Factories receive
   only `ResolvedModuleEnvironment`, not `os.environ`, core services, database
   records, browser tokens, or UI objects.
4. Bound every validation, search, intermediate resolve, magnet, and torrent
   response before decoding or buffering. Enforce both declared and streamed
   bytes, strict JSON/text, raw and returned result counts, private-selection
   size, and artifact limits. Resolve only a core-held opaque selection into an
   in-memory magnet or torrent artifact; do not retry ambiguous operations unless
   an approved contract defines idempotency and reconciliation.
5. Build snapshots with the SDK's canonical safe GUID, infohash, and public-page
   rules. Runtime DTOs, executable conformance, serialized conformance, generated
   schemas, and core defensive validation must accept and reject the same boundary
   corpus. Map upstream failures to stable safe `ModuleError` data without
   credentials, passkeys, sensitive URLs, selections, response bodies, or
   artifacts.
6. Keep logging lifecycle-safe. A module may redact its own records, but must not
   install unowned process-global filters or handlers. Process-wide HTTP logging
   policy belongs to the host lifespan with identity-owned cleanup. Test the
   actual emitting logger names and ensure close is idempotent.
7. Use deterministic fake transports and
   `assert_release_registration_conforms` for required configuration, bounded
   validation/search/resolve, safe snapshots, every declared artifact kind,
   standardized failures, redaction/logging, and idempotent double close.
   Prowlarr is a contract example, not a template for its URL policy, API-key
   flow, parser, or error codes.
8. Add hash-bound `fixtures/conformance.json` validated against
   `schemas/module-sdk/v1/conformance.schema.json`. Store only safe serialized
   descriptors; never serialize private selections, magnets, torrent bytes,
   credentials, raw responses, or download URLs. Bind deterministic runtime
   outputs and failures to the same serialized expectations.
9. Register the public registration explicitly in
   `apps/server/src/media_finder_server/modules.py`. If replacing acquisition
   behavior, change `SELECTED_RELEASE_MODULE_ID` explicitly in the same review;
   registration order must never select a provider.
10. Run focused package and SDK tests, `pnpm module-conformance:test`,
   `pnpm module-conformance:validate`,
   `uv run pytest tests/architecture/test_package_boundaries.py tests/test_wheel_isolation.py`,
   format, lint, type, and `pnpm spec:validate`.

Do not add dynamic discovery, a generic plugin/service layer, module routes,
module persistence, or a serialized fixture in place of executable conformance.
