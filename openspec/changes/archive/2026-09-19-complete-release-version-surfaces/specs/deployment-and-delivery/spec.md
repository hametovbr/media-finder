## MODIFIED Requirements

### Requirement: Reproducible release candidate
Release preparation SHALL update all lockstep product versions and required version-derived conformance artifacts without dependency upgrades or API/SDK/schema-version changes. The set of version-derived surfaces SHALL be derived from the previous stable release commit rather than enumerated by hand, and SHALL include every surface that a release commit of this repository updates, including the product version the running server reports. Preparation SHALL fail, rather than publish, when a version-derived surface that the previous stable release commit updated is absent from the prepared tree. Before merge, automation SHALL reproduce the entire expected tree from the recorded base, requested version and captured release-note inputs. The review exemption SHALL require authenticated automation provenance, the expected repository/base and exact generated content; branch names, labels and changed-path allowlists alone SHALL NOT suffice.

#### Scenario: Prepare lockstep versions
- **WHEN** a release candidate is generated
- **THEN** all nine workspace distributions, first-party module manifests, UI package metadata, workspace lock entries and bound conformance versions/hashes agree and existing version/conformance checks pass

#### Scenario: A version-derived surface is missing
- **WHEN** the prepared tree omits a surface that the previous stable release commit updated, such as the product version the running server reports
- **THEN** preparation or the candidate gate fails with a reported omission instead of publishing a tree whose reported version is stale

#### Scenario: Candidate tests run on a prepared tree
- **WHEN** the repository's own tests execute against a prepared release candidate rather than the pre-release tree
- **THEN** they assert the candidate's versions without depending on the version the tree happened to carry before preparation

#### Scenario: Alter a release PR
- **WHEN** a candidate contains extra edits, unexpected dependency changes, altered generated values, or lacks authentic provenance
- **THEN** automation refuses automatic merge and reports the mismatch without overwriting those changes
