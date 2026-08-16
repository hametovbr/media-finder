---
name: adding-metadata-provider
description: Use when adding, replacing, or changing a Media Finder metadata-provider module, its manifest, normalization, retention, environment contract, fixtures, or conformance.
---

# Adding a Metadata Provider

Add one statically packaged module; core keeps persistence, transactions,
selection, and generic lifecycle ownership.

1. Use the applicable approved OpenSpec change and TDD: add a deterministic
   failing behavior/contract test before implementation. Update the OpenSpec
   delta when normalized data, retention, configuration, or public contracts
   change.
2. Create `packages/modules/metadata-<name>/` as an independent wheel. Its
   import package exposes only `registration()` returning a
   `MetadataProviderRegistration`; it imports only `media_finder_sdk` and its
   own libraries. Add its workspace entry, direct host dependency in
   `apps/server/pyproject.toml`, lockfile, `Dockerfile` wheel assembly, and
   deterministic package/delivery inventories in the same change.
3. Put identity, `metadata-provider` kind, capabilities (`search`, `fetch`,
   `normalize`, plus any declared optional capability), attribution,
   translations, compatibility, and exact value-free environment declarations
   in `src/<package>/module.toml`. Match every key in `translations/en.json` and
   `translations/ru.json`. Receive only `ResolvedModuleEnvironment`; never read
   `os.environ`, persist configuration, or expose secrets.
4. Bound every upstream read before decoding, including authentication and
   validation endpoints. Enforce declared and streamed bytes, strict JSON,
   depth/nodes/counts/text, and finite portable numbers. Before fan-out, validate
   and deduplicate the complete reference set, enforce per-response and aggregate
   request/result budgets, and cap concurrency. Revalidate all SDK output; map
   failures to stable safe `ModuleError` data without bodies, credentials, or
   sensitive URLs.
5. Use SDK DTOs and provider-owned retention. If declaring `metadata-edit`,
   supply its typed editor factory. Module-owned transports close idempotently;
   core owns persistence, template rendering, and final lifecycle.
6. Add executable tests using
   `assert_metadata_registration_conforms` and, if declared,
   `assert_metadata_editor_registration_conforms`. Exercise real deterministic
   fixtures, required-variable failures, locale/identity, normalization,
   attribution, redaction, limits, retention, and double close.
7. Add `fixtures/conformance.json` matching the raw `module.toml` hash and
   `schemas/module-sdk/v1/conformance.schema.json`. It records safe serialized
   behavior only—no credentials, raw payloads, or artifacts. Bind deterministic
   runtime search/fetch/normalize, retention, failure, and redaction cases to the
   same serialized expectations so neither representation can drift. Update
   generated `schemas/module-sdk/v1/` artifacts when SDK contract shapes change.
8. Add the public registration explicitly in
   `apps/server/src/media_finder_server/modules.py`; never give core a concrete
   import or identifier branch. Run focused package/SDK tests,
   `pnpm module-conformance:test`, `pnpm module-conformance:validate`,
   `uv run pytest tests/architecture/test_package_boundaries.py tests/test_wheel_isolation.py`,
   then format, lint, type, and `pnpm spec:validate`.

Do not clone provider-specific policy into core, add a generic plugin loader,
or treat a serialized fixture as a substitute for executable conformance.
