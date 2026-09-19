## MODIFIED Requirements

### Requirement: Verified stable publication and resumable failure
Automation SHALL bind the release tag to the exact accepted merged commit after successful verification and main/edge publication for that commit. It SHALL create and inspect a draft stable GitHub Release before publishing it. Completion SHALL require actual GHCR evidence for the immutable full-version tag, intended minor/latest tags, matching digest, both supported architectures and source revision. It SHALL never move an existing stable Git tag, overwrite an immutable image with a rebuilt digest, or replace newer moving tags with an older release. Failures SHALL report the completed boundary and permit identity-checked resumption. Registry absence SHALL be established from the diagnostic the registry tooling actually emits for a missing manifest, and SHALL NOT be inferred from authentication, authorisation, network, timeout or transport diagnostics. A blocked publication SHALL record the diagnostic that identifies its cause, so the operator can act without reproducing the failure elsewhere.

Publication SHALL also be reachable through an authorized, main-only manual entry point that names an existing stable release tag, so that the current trusted publisher can complete a release whose image is missing or incomplete. That entry point SHALL resolve the named release and refuse to publish unless it exists, is published, is neither a prerelease nor a draft, its tag equals the version at the release commit it publishes, and that commit carries the required verification contexts as check runs of the GitHub Actions application. It SHALL publish the source at that release commit using the trusted logic of the revision that dispatched it, and SHALL leave the tag, its target and any existing immutable image untouched. Reading an existing moving tag SHALL interpret the version-label conventions this project has published, including a leading `v`, so that reconciling with an earlier release stays possible; the ordering and immutability decisions SHALL remain based on the interpreted version and SHALL NOT be relaxed by that tolerance.

Each entry point SHALL act only for the event it belongs to and SHALL publish only the revision it resolved. A guard SHALL NOT depend on a field that is absent for the event under which it is evaluated, and a resolved revision SHALL be supplied through a mechanism that can actually replace the platform's own default value rather than one the platform reserves. Publication SHALL NOT depend on build environment that the publishing step cannot itself supply.

#### Scenario: Main advances after release merge
- **WHEN** an unrelated commit reaches main while release verification is pending
- **THEN** release identity remains the accepted merged SHA and unrelated success cannot satisfy its gates

#### Scenario: Publish and verify
- **WHEN** publication finishes successfully
- **THEN** the summary identifies PR and merged SHA, release/workflow URLs, all three actual tags, digest and linux/amd64 plus linux/arm64 manifests with matching source provenance

#### Scenario: Repair a release whose image is missing
- **WHEN** an authorized maintainer requests publication for an existing stable release whose image was never published, and the current trusted publisher contains a fix the release commit predates
- **THEN** the image is published from the release commit's source using the current trusted publisher, and the tag, its target commit and the release object are unchanged

#### Scenario: Each entry point acts only for its own event
- **WHEN** the manual entry point runs for an existing stable release
- **THEN** the release-event publication job does not run, and when a release event runs, the manual job does not run

#### Scenario: Publish the resolved revision
- **WHEN** the manual entry point publishes a release
- **THEN** the revision the publisher asserts is the resolved release commit, not the revision that dispatched the workflow

#### Scenario: Build without environment the step cannot supply
- **WHEN** publication has to build an image rather than reuse an existing immutable manifest
- **THEN** the build succeeds using only environment the publishing step itself provides

#### Scenario: Refuse an unverifiable repair request
- **WHEN** the named tag has no release, is a draft or prerelease, does not equal the version at the commit it would publish, or that commit lacks a required verification context
- **THEN** no image is published and the request is reported as refused

#### Scenario: First publication has no immutable tag yet
- **WHEN** publication runs before the immutable image tag exists and the registry tooling reports that the manifest is missing
- **THEN** absence is established and publication proceeds, while an authentication, authorisation, transport or timeout diagnostic still stops the run

#### Scenario: Report a blocked publication
- **WHEN** a registry command fails for a reason other than absence
- **THEN** the failure record and the workflow summary carry the diagnostic that identifies the cause

#### Scenario: Recover from partial publication
- **WHEN** a timeout or failure occurs after a PR, merge, draft, release or image already exists
- **THEN** a retry verifies that existing state before continuing, preserves immutable identities and never reports success while required publication evidence is missing

#### Scenario: Reconcile a moving tag published by an earlier release
- **WHEN** a moving tag already points at an earlier release whose version label carries a leading `v`
- **THEN** the existing image is recognised as that earlier release, publication continues, and the moving tag is only moved forward after the new digest is verified

#### Scenario: Reject conflicting existing release
- **WHEN** a version tag, release or image resolves to an unexpected target, or an older request would roll moving tags backward
- **THEN** publication stops without replacing the conflicting or newer state
