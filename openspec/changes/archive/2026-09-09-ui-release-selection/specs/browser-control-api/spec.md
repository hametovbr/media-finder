## ADDED Requirements

### Requirement: Bounded release comparison projection
Release-search responses SHALL retain the existing optional numeric fields `size` and `seeders`. Size SHALL express positive bytes and seeders SHALL express a nonnegative count, each bounded by 9007199254740991; null or omission SHALL mean unknown. The documented OpenAPI and generated consumers SHALL match these bounds. This coordinated version-1 evolution SHALL preserve responses with omitted optional fields without promising that old strict schema readers accept newly populated fields. No private release-provider data SHALL accompany these facts.

#### Scenario: Project known and unknown facts
- **WHEN** the release gateway returns known size, zero seeders or unknown metrics
- **THEN** HTTP serialization preserves the known integers and unknown values without converting unknown to zero or exposing resolution data

#### Scenario: Regenerate the browser contract
- **WHEN** control OpenAPI and built-in client types are generated from the owning models
- **THEN** they describe the same optional field names and numeric semantics as gateway and HTTP conformance tests
