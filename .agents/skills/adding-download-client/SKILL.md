---
name: adding-download-client
description: Use when adding, replacing, or changing a Media Finder download-client module, its destination discovery, magnet or torrent submission, exact correlation lookup, manifest, typed configuration, fixtures, or client conformance tests. Do not use for Prowlarr search, metadata providers, media-file processing, progress monitoring, or unrelated acquisition UI changes.
---

# Adding a Download Client

## Core principle

Implement the smallest submission adapter behind the public client contract. Media Finder hands off a torrent artifact once, correlates an ambiguous result exactly, and then stops; the download client owns progress and completion.

## Workflow

1. Read `AGENTS.md`, the active OpenSpec change, the Acquisition state contract, and the current download-client protocol.
2. Propose or update OpenSpec requirements when behavior, artifact support, destination semantics, configuration, or the public contract changes. Do not implement before approval.
3. Establish a failing conformance or behavior test with a deterministic fake transport.
4. Add a statically packaged module with:
   - a stable client key, manifest, and capabilities;
   - typed Pydantic configuration, translation keys, and an ordered immutable declaration of every exact environment variable;
   - configuration validation and safe standardized errors;
   - live destination listing;
   - magnet URI and/or in-memory `.torrent` byte submission as declared;
   - exact correlation-token preservation and lookup;
   - fixtures and a conformance-suite factory.
5. Make the registration's exact environment declarations the only configuration source. Core resolves only those names into the builder's in-memory mapping; there is no database payload, operator-selected `env:NAME` reference, fallback, precedence, alias, or dynamic prefix. Mark each variable required/optional and secret/non-secret, provide its translation key, and never persist its value or an environment reference. Never return or log credentials, magnet URIs, torrent bytes, download URLs, passkeys, or raw upstream exception content.
6. Accept the correlation token from core unchanged. Do not generate, normalize, prefix, truncate, or encode it. Core supplies `mf-acq-<uuid>`.
7. Reload destinations immediately before submission and reject a destination no longer returned by the client. Map the selected destination using that client's native semantics.
8. On submission timeout, support exact `find_by_correlation`. Do not resubmit inside the module and do not infer acceptance from title, hash similarity, or destination alone.
9. Run focused tests, `assert_client_registration_conforms` for the exact environment contract and production builder, shared client behavior conformance tests, type/lint checks, documentation-policy checks, and strict OpenSpec validation.

## Contract boundary

| Module owns | Core owns |
| --- | --- |
| Native authentication and protocol | Acquisition persistence and idempotency |
| Live destination discovery | Destination choice and revalidation |
| Native artifact submission | In-memory artifact resolution |
| Exact correlation storage and lookup | `mf-acq-<uuid>` generation |
| Safe transport-error translation | `pending`, `submitted`, `failed` transitions |

The module must not receive a database session, application repository, Jinja environment, template path, or writable artifact path.

## State constraints

Do not add queued, downloading, stalled, completed, imported, or seeding states. A definitive acceptance becomes `submitted`; a definitive rejection becomes `failed`; an ambiguous timeout is resolved by exact correlation or left `pending` for manual reconciliation. Startup never auto-resubmits a pending Acquisition.

## Test recipe

Pass independent literal declarations and fixture values to `assert_client_registration_conforms`; it must verify exact names/classifications, every required-variable omission, and successful production construction before behavior conformance runs. Then run the same behavior cases against a fixture-backed client factory: valid/invalid configuration, destination listing, supported artifact forms, exact correlation preservation, lookup hit/miss, safe errors, and absence of database/template access. Add adapter-specific tests for authentication negotiation, native destination mapping, timeout ambiguity, redaction, and inputs containing Unicode or special characters.

## Example

For a client whose native destination is a filesystem directory, return its allowed directories from live discovery and map the user's selected value directly to the native submission field. Attach the exact correlation token in a native label/comment field and look up by that exact field. Do not invent Media Finder progress states or persist the resolved magnet.

## Common mistakes

- Polling client progress or adding completion states.
- Persisting magnet URIs, torrent bytes, download URLs, or passkeys.
- Persisting integration settings or operator-selected environment references.
- Supporting precedence or fallback between environment and persisted integration configuration.
- Using a configured stale destination list instead of live discovery.
- Rewriting the correlation token or matching only by release title/hash.
- Retrying automatically after an ambiguous timeout.
- Giving the module database or UI-template access.

## Completion checklist

- Approved OpenSpec behavior and contract
- Failing test observed before implementation
- Manifest, typed config, exact environment declarations, translations, fixtures
- Live destinations and supported in-memory artifact forms
- Exact correlation preservation and lookup
- Timeout and secret-redaction tests
- Registration and behavior conformance suites passing without DB/template access
- Strict OpenSpec and repository checks passing
