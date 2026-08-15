---
name: adding-metadata-provider
description: Use when adding, replacing, or changing a Media Finder metadata-provider module, its manifest, configuration, normalization, attribution, retention policy, fixtures, or provider conformance tests. Do not use for editing one item's Manual metadata, release search, download clients, naming-only changes, or unrelated core features.
---

# Adding a Metadata Provider

## Core principle

Add a statically packaged adapter behind the public provider contract. Keep provider rules—including refresh, expiry, attribution, and upstream quirks—inside the module; keep database and UI-template access outside it.

## Workflow

1. Read `AGENTS.md`, the active OpenSpec change, and the current metadata-provider contract before editing.
2. Propose or update OpenSpec requirements when behavior, normalized metadata, configuration, retention, or public contracts change. Do not implement before approval.
3. Establish a failing contract or behavior test using deterministic fixtures.
4. Add an isolated package with:
   - a stable provider key and manifest;
   - capabilities and typed Pydantic configuration;
   - translation keys and generic-form metadata;
   - configuration validation and standardized safe errors;
   - search, fetch, normalization, provenance, and attribution;
   - provider-owned retention planning and execution hooks;
   - fixtures and a conformance-suite factory.
5. Keep secrets in environment variables and persist only `env:NAME` references. Redact credentials, tokens, sensitive URLs, raw payload fragments, and upstream exception text.
6. Normalize into the versioned public schema. Preserve provider identity, locale, completeness, structural quality, seasons, episodes, and Season 00 specials when supplied. Never auto-merge identities from different providers.
7. Make retention explicit. The module computes calendar dates and returns generic actions; core only schedules and applies those actions. Retain revision envelopes, identity, overrides, and acquisition history when derived payload is purged.
8. Run focused tests, the shared provider conformance suite, type/lint checks, documentation-policy checks, and strict OpenSpec validation.

## Contract boundary

| Module owns | Core owns |
| --- | --- |
| Upstream protocol and mapping | Persistence and transactions |
| Provider configuration schema | Generic settings rendering |
| Attribution and provenance | Revision orchestration |
| Refresh and expiry semantics | Provider-agnostic maintenance schedule |
| Fixture-backed upstream behavior | Shared conformance runner |

The module must not receive a database session, application repository, Jinja environment, template path, arbitrary HTML, or JavaScript.

## Test recipe

Use one provider factory with recorded or synthetic fixtures. Cover valid and invalid configuration, requested locales, search/fetch mapping, stable external identity, standardized errors, secret redaction, attribution, and no database/template dependency. If the provider expires data, use a fake clock to test boundary dates, refresh, purge, retained envelope fields, and `metadata_source_expired` export behavior.

## Example

For a provider whose terms allow six months of caching, compute its refresh and expiry timestamps inside that provider package. Return public maintenance actions from its hook and test them with a fake clock. Do not add the provider name or six-month duration to core maintenance code.

## Common mistakes

- Encoding a provider-specific TTL in core or a global setting.
- Returning raw upstream payloads through public APIs.
- Storing resolved credentials or passkey-bearing URLs.
- Adding provider-specific templates instead of typed generic settings.
- Mocking the module internals instead of exercising the public conformance contract.
- Treating title/year similarity as cross-provider identity.

## Completion checklist

- Approved OpenSpec behavior and contract
- Failing test observed before implementation
- Manifest, typed config, translations, attribution, fixtures
- Search, fetch, normalize, provenance, safe errors
- Module-owned retention hooks or explicit no-expiry behavior
- Shared conformance suite passing without DB/template access
- Secrets and logs verified safe
- Strict OpenSpec and repository checks passing
