## ADDED Requirements

### Requirement: Portable release search metrics
The release SDK SHALL support optional search-only size in bytes and seeder count independently of the safe release snapshot. Size SHALL be an integer from 1 through 9007199254740991; seeders SHALL be an integer from 0 through 9007199254740991. Omitted or null values SHALL mean unknown. Integral JSON numbers such as 1.0 SHALL be accepted; booleans, strings, fractional numbers, non-finite values and values outside these bounds SHALL be rejected at the public boundary. Runtime, executable conformance, serialized conformance and deterministic schemas SHALL agree on these semantics.

#### Scenario: Provider omits optional metrics
- **WHEN** a conforming provider or version-1 fixture omits search metrics
- **THEN** the updated SDK accepts the result with unknown metrics without changing its safe snapshot or private resolution data

#### Scenario: Portable metric boundary corpus
- **WHEN** the same metric corpus is checked by runtime and serialized conformance validators
- **THEN** null, omission, integral 1.0, the maximum and zero seeders are accepted, while zero size, booleans, numeric strings, fractions, non-finite values and out-of-range numbers are rejected

#### Scenario: Invalid constructed candidate crosses core boundary
- **WHEN** a provider bypasses normal construction and returns a candidate with invalid metrics
- **THEN** defensive validation rejects it before caching or browser projection without logging private selection data
