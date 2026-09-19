## MODIFIED Requirements

### Requirement: Verified stable publication and resumable failure
Automation SHALL bind the release tag to the exact accepted merged commit after successful verification and main/edge publication for that commit. It SHALL create and inspect a draft stable GitHub Release before publishing it. Completion SHALL require actual GHCR evidence for the immutable full-version tag, intended minor/latest tags, matching digest, both supported architectures and source revision. It SHALL never move an existing stable Git tag, overwrite an immutable image with a rebuilt digest, or replace newer moving tags with an older release. Failures SHALL report the completed boundary and permit identity-checked resumption. Registry absence SHALL be established from the diagnostic the registry tooling actually emits for a missing manifest, and SHALL NOT be inferred from authentication, authorisation, network, timeout or transport diagnostics. A blocked publication SHALL record the diagnostic that identifies its cause, so the operator can act without reproducing the failure elsewhere.

#### Scenario: Main advances after release merge
- **WHEN** an unrelated commit reaches main while release verification is pending
- **THEN** release identity remains the accepted merged SHA and unrelated success cannot satisfy its gates

#### Scenario: Publish and verify
- **WHEN** publication finishes successfully
- **THEN** the summary identifies PR and merged SHA, release/workflow URLs, all three actual tags, digest and linux/amd64 plus linux/arm64 manifests with matching source provenance

#### Scenario: First publication has no immutable tag yet
- **WHEN** publication runs before the immutable image tag exists and the registry tooling reports that the manifest is missing
- **THEN** absence is established and publication proceeds, while an authentication, authorisation, transport or timeout diagnostic still stops the run

#### Scenario: Report a blocked publication
- **WHEN** a registry command fails for a reason other than absence
- **THEN** the failure record and the workflow summary carry the diagnostic that identifies the cause

#### Scenario: Recover from partial publication
- **WHEN** a timeout or failure occurs after a PR, merge, draft, release or image already exists
- **THEN** a retry verifies that existing state before continuing, preserves immutable identities and never reports success while required publication evidence is missing

#### Scenario: Reject conflicting existing release
- **WHEN** a version tag, release or image resolves to an unexpected target, or an older request would roll moving tags backward
- **THEN** publication stops without replacing the conflicting or newer state
