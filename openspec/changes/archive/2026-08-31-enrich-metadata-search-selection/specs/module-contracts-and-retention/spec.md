## MODIFIED Requirements

### Requirement: Metadata-provider contract
A metadata-provider module SHALL expose its exact environment-variable requirements, configuration validation, successful search, successful identity-based fetch, normalization, attribution, standardized errors, provider-owned retention hooks, and a typed export-warning hook without direct database or UI-template access. Every provider manifest SHALL advertise `search`, `fetch`, and `normalize` as essential capabilities. The version-1 metadata search-result contract SHALL accept an optional nullable plain-text `description` and an optional nullable complete `poster_url`; a module that does not provide either preview field SHALL remain conforming. When a module provides `poster_url`, that module SHALL construct the complete provider-appropriate URL. Core, control, and presentation consumers SHALL only validate the shared value contract and preserve the module-produced URL without constructing, rewriting, or branching on a concrete provider. The export-warning hook SHALL return only deeply immutable, allowlisted, validated response-header values or no warning. Core SHALL defensively revalidate returned search results and warnings before consuming them.

#### Scenario: Conform an external provider
- **WHEN** a test provider implements the public metadata contract using only its fixtures and public types
- **THEN** the shared conformance suite requires exact environment declarations and an expected safe error code and unconditionally validates successful search, fetch, normalization, locale, identity, optional search previews, that standardized error, attribution, retention, missing-variable behavior, and secret classification without knowledge of provider internals

#### Scenario: Conform a provider without previews
- **WHEN** a metadata-provider module omits `description` and `poster_url` from a version-1 serialized search result or returns them as null
- **THEN** the SDK schema and shared conformance accept the result and downstream consumers treat both previews as absent

#### Scenario: Preserve a module-produced poster URL
- **WHEN** a metadata-provider module returns a search result containing a valid complete `poster_url`
- **THEN** core defensively validates and caches that exact URL without adding a host, size path, provider branch, or other transformation

#### Scenario: Conform the Manual provider
- **WHEN** the Manual provider is supplied an in-memory conformance fixture identity
- **THEN** it declares no required environment variables and searches and fetches that fixture through the same public protocol without database or UI access

#### Scenario: Supply an export warning
- **WHEN** a provider has a retention deadline that external processors need to know
- **THEN** its export-warning hook returns validated safe headers through the public provider contract without a provider-specific core branch
