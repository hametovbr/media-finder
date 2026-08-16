---
name: evolving-metadata-schema
description: Use when changing normalized Media Finder metadata fields, hierarchy, schema versions, provider mappings, overrides, APIs, naming inputs, NFO projections, or serialized schema artifacts.
---

# Evolving the Metadata Schema

Normalized metadata is a versioned public contract. Change the contract once,
then update every producer, consumer, executable fixture, and serialized
artifact that relies on it.

1. Before choosing compatibility, inventory actual stored data, deployed users,
   external processor/control clients, replacement UIs, and third-party modules.
   Characterize exact current Python DTO, JSON/OpenAPI, executable/serialized
   fixture, persisted revision, current-read, and pinned-read behavior. “Internal
   rename,” product release, and “no known users” do not authorize a wire change.
2. Use an approved OpenSpec delta before implementation. Record the schema and
   wire version decision, immutable old-revision policy, current/pinned and
   API/export behavior, migration/rollback decision, and this complete trace:
   provider/Manual/import/override → stored revision/effective snapshot →
   control/processor API → naming/NFO/UI → retention.
3. Add deterministic RED contract tests for the new and every supported stored
   version. Choose one explicit old-version policy: read/project unchanged,
   translate at one boundary, migrate with recovery, or reject safely. Do not
   rewrite immutable revision payloads, scatter dual-read aliases, or add
   compatibility without evidence of a real obligation.
4. Update the canonical SDK models in
   `packages/module-sdk/src/media_finder_sdk/types.py` and related validation,
   then regenerate/check the deterministic artifacts in `schemas/module-sdk/v1/`.
   Update module `module.toml` capabilities only if their declared contract
   changes; manifests never contain values or schema payloads.
5. Update every producer (Manual, provider normalizers, imports, overrides, and
   executable fixtures) and consumer (effective snapshots, control/processor
   DTOs, naming, NFO, UI, retention). Preserve locale, provenance, completeness,
   structural quality, and specials semantics.
6. Update each affected module's executable conformance with
   `assert_metadata_registration_conforms` (and
   `assert_metadata_editor_registration_conforms` when declared), plus its
   hash-bound `fixtures/conformance.json`. The serialized file must validate
   independently against `schemas/module-sdk/v1/conformance.schema.json`.
7. Run focused schema/provider/API/naming/NFO/retention tests,
   `pnpm module-conformance:test`, `pnpm module-conformance:validate`,
   `uv run pytest tests/architecture/test_package_boundaries.py tests/test_wheel_isolation.py`,
   schema drift, format, lint, type, and `pnpm spec:validate`.

Do not create a generic schema registry, mutate historical revisions, or let a
Python-only change drift from JSON Schema, fixtures, and public serialized APIs.
