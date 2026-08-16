---
name: evolving-media-finder-contracts
description: Use when changing Media Finder control or processor APIs, SDK DTOs or errors, module manifests, OpenAPI, JSON Schema, serialized conformance, validation bounds, or public field semantics.
---

# Evolving Media Finder Contracts

Treat every public representation as one versioned contract. Internal cleanup
does not authorize a wire, schema, persistence-history, or fixture change.

## Characterize before changing

1. Identify the approved OpenSpec requirement and exact contract/version.
2. Capture current HTTP JSON, status/error behavior, headers, OpenAPI, SDK model
   serialization, manifest/schema output, and serialized fixture behavior that
   consumers can observe.
3. Trace every producer and consumer: module transport and normalization, SDK,
   core persistence/application services, control/processor projection, built-in
   UI, external UI, naming/NFO/export, fixtures, independent validator, and docs.
4. Check actual users, stored data, generated clients, external consumers, and
   coordinated rollout ability before deciding compatibility.

## Make the version decision

- Preserve an existing version with an explicit boundary projection when an
  internal name or model changes but approved wire behavior does not.
- Additive changes require approved semantics, deterministic artifacts, and
  tolerant consumers.
- Breaking wire semantics require an approved new contract/API version and a
  defined old-version read/deprecation policy. A product release version alone
  does not version an API or SDK contract.
- Never emit two aliases indefinitely without an approved transition and removal
  point.

## Keep representations aligned

Define each bound and semantic once at the owning public contract. Apply it to:

- runtime parsing and defensive revalidation;
- Python DTOs and error envelopes;
- generated OpenAPI and JSON Schema;
- executable conformance;
- serialized fixtures and the independent non-core validator.

Use exact portable units and rules: encoded bytes versus characters, finite JSON
numbers, depth/node/count/fan-out limits, safe public URL/GUID policy, redaction,
locale/provenance identity, artifact kinds, and correlation. Approximate runtime
limits must not be published as exact language-neutral bounds.

## RED–GREEN sequence

Add characterization first and observe RED for the intended contract gap. Update
the owner, adapters, generated artifacts, fixtures, consumers, and docs in one
slice. Regenerate deterministic artifacts; do not hand-edit generated output.
Run contract, conformance, OpenAPI/schema drift, control/processor, module, and
consumer regressions.

## Stop conditions

Use `openspec-update-change` when field meaning, versioning, compatibility,
stored-version behavior, error codes, security semantics, or portable bounds are
not already decided. Do not infer permission from “no known users,” an internal
rename, or a passing model test.

Report the old contract, approved decision, producer/consumer trace, exact
artifacts changed, compatibility/rollback, and evidence that all representations
agree.
