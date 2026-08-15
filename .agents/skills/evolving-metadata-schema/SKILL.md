---
name: evolving-metadata-schema
description: Use when adding, removing, renaming, retyping, or changing semantics of normalized Media Finder metadata fields, hierarchy, schema versions, overrides, provider mappings, metadata APIs, naming inputs, or NFO projections. Do not use for provider-only raw payload changes, UI copy, database columns unrelated to normalized metadata, or editing one Manual media item.
---

# Evolving the Metadata Schema

## Core principle

Treat normalized metadata as a versioned public contract shared by immutable revisions, providers, APIs, naming, NFO, imports, and overrides. Change it once at the contract boundary, then update every producer and consumer deliberately.

## Workflow

1. Read `AGENTS.md`, the active OpenSpec specs, the normalized schema, current stored revision versions, public API examples, provider contracts, naming, and NFO projections.
2. Inventory real consumers and stored data before choosing compatibility. Distinguish:
   - additive optional data;
   - required or retyped data;
   - renamed or removed data;
   - hierarchy or semantic changes.
3. Propose and obtain approval for an OpenSpec change. State the new `schema_version`, old-revision behavior, import/export behavior, API shape, override rules, and migration/rollback boundary.
4. Write failing contract tests for the new shape and regression tests for every supported stored version before changing production code.
5. Update the canonical schema and public SDK types. Define nullability, representation, locale/provenance semantics, completeness impact, structural-quality impact, and validation rules.
6. Update every producer: Manual forms/imports, provider normalizers, fixtures, test providers, and user overrides. A provider must emit one unambiguous declared version.
7. Update every consumer: effective-snapshot merging, current and pinned metadata APIs, naming inputs, NFO mapping, retention/purge behavior, UI rendering, examples, and conformance suites.
8. Preserve immutable stored revision payloads. Never rewrite a prior revision in place. Add a read adapter or explicit old-version response only when existing persisted revisions or active external consumers require it.
9. Add a database migration only when relational storage or indexes change. JSON shape changes alone do not justify a bulk rewrite.
10. Run schema, provider, import, API, naming, NFO, expiry, migration, and rollback tests plus strict OpenSpec and repository checks.

## Compatibility decision

| Evidence | Action |
| --- | --- |
| No released consumer and no stored old revision | Make the coordinated change without aliases |
| Stored immutable old revisions exist | Keep them intact and define explicit read/export behavior |
| Active external consumer needs transition | Add a time-bounded documented adapter or versioned endpoint |
| Hypothetical future consumer only | Do not add compatibility machinery |

Do not silently coerce two field names, emit both indefinitely, or strip a stored revision's original `schema_version`.

## Impact trace

For each changed field, record this chain in the OpenSpec design or task notes:

`provider/manual input → normalized revision → overrides/effective snapshot → API → naming/NFO/UI`

Mark each stage as changed, intentionally unchanged, or not applicable. Also trace expiry and purging so adapters never depend on deleted provider payloads.

## Test recipe

Create table-driven examples for the old supported versions and the new version. Cover valid/invalid payloads, immutable pinned acquisitions, current revisions, overrides, Manual JSON/CSV atomicity, every provider mapping, public API schema version, naming snapshots, XML escaping/projection, and expired provider-derived data. Test upgrade and rollback using a copied database when relational migration is involved.

## Example

When renaming normalized `plot` to `summary`, bump the schema version and update providers plus effective snapshots. NFO may still emit the external `<plot>` element because that is the Jellyfin/Kodi contract, not the normalized field name. Preserve stored v1 revisions. Add a v1 reader only if those revisions can exist; do not emit both `plot` and `summary` merely for speculative compatibility.

## Common mistakes

- Changing Pydantic models without updating providers, imports, NFO, or examples.
- Rewriting immutable historical revisions during migration.
- Adding aliases or version negotiation without a real consumer.
- Confusing provider raw JSON changes with normalized schema changes.
- Losing provenance, locale, completeness, or special-episode structure.
- Mapping an internal rename directly onto an incompatible external XML field name.

## Completion checklist

- Approved OpenSpec contract and migration decision
- New schema version and field semantics documented
- Failing contract/regression tests observed
- All producers and consumers traced and updated
- Old immutable revisions preserved with evidence-based compatibility
- Provider conformance, Manual import, API, naming, NFO, and expiry tests passing
- Backup/rollback documented when persistence changes
- Strict OpenSpec and repository checks passing
