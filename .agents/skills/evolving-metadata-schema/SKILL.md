---
name: evolving-metadata-schema
description: Use when changing normalized Media Finder metadata fields, hierarchy, schema versions, provider mappings, overrides, APIs, naming inputs, NFO projections, or serialized schema artifacts.
---

# Evolving the Metadata Schema

Normalized metadata is a versioned public contract. Change the contract once,
then update every producer, consumer, executable fixture, and serialized
artifact that relies on it.

1. Use an approved OpenSpec delta before implementation. Record the new schema
   version, old immutable-revision behavior, API/export behavior, migration
   decision, and this trace: provider/Manual input → revision → override/effective
   snapshot → API → naming/NFO/UI → retention.
2. Add deterministic RED contract tests for the new and every supported stored
   version. Do not rewrite immutable revision payloads or add aliases without a
   real stored-data or external-consumer requirement.
3. Update the canonical SDK models in
   `packages/module-sdk/src/media_finder_sdk/types.py` and related validation,
   then regenerate/check the deterministic artifacts in `schemas/module-sdk/v1/`.
   Update module `module.toml` capabilities only if their declared contract
   changes; manifests never contain values or schema payloads.
4. Update every producer (Manual, provider normalizers, imports, overrides, and
   executable fixtures) and consumer (effective snapshots, control/processor
   DTOs, naming, NFO, UI, retention). Preserve locale, provenance, completeness,
   structural quality, and specials semantics.
5. Update each affected module's executable conformance with
   `assert_metadata_registration_conforms` (and
   `assert_metadata_editor_registration_conforms` when declared), plus its
   hash-bound `fixtures/conformance.json`. The serialized file must validate
   independently against `schemas/module-sdk/v1/conformance.schema.json`.
6. Run focused schema/provider/API/naming/NFO/retention tests,
   `pnpm module-conformance:test`, `pnpm module-conformance:validate`,
   `uv run pytest tests/architecture/test_package_boundaries.py tests/test_wheel_isolation.py`,
   schema drift, format, lint, type, and `pnpm spec:validate`.

Do not create a generic schema registry, mutate historical revisions, or let a
Python-only change drift from JSON Schema, fixtures, and public serialized APIs.
