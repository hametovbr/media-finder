# Security Finding Governance Specification

## Purpose

Define a secret-safe, time-bounded, and independently verifiable repository contract for triaging security findings and governing exceptional suppressions.

## Requirements

### Requirement: Owned security finding lifecycle
Every security finding produced by repository review, secret scanning, static analysis, dependency analysis, filesystem analysis, or image analysis SHALL be triaged to exactly one current disposition: resolved, unresolved, or covered by an active security exception. The triage record SHALL identify a responsible owner and a safe tracking reference, and it SHALL preserve the scanner and finding identity without copying credentials, authenticated URLs, exploit material, or other sensitive evidence into the repository.

A finding that violates an approved blocking policy SHALL prevent the affected change or artifact from passing unless the finding is resolved or covered by an active exception. Advisory findings SHALL remain visible for remediation or explicit reclassification rather than disappearing through an unrecorded ignore.

#### Scenario: Blocking finding is unresolved
- **WHEN** a repository security gate reports a finding that violates its approved blocking policy and no active exception covers the exact finding and scope
- **THEN** verification remains failed and the finding is assigned to an owner for remediation

#### Scenario: Advisory finding remains open
- **WHEN** a scanner reports a finding below its approved blocking threshold
- **THEN** the finding remains observable with an owner and safe tracking reference until it is resolved, reclassified, or covered by an active exception

#### Scenario: Sensitive finding is tracked
- **WHEN** a finding contains a credential, authenticated URL, exploit detail, or other sensitive evidence
- **THEN** the repository records only safe identifiers and a non-sensitive tracking reference while the sensitive evidence remains in an access-controlled channel

### Requirement: Versioned security exception contract
The repository SHALL maintain one versioned, machine-validated security-exception manifest. Each exception SHALL have a unique stable identifier and SHALL record the scanner, finding identifier, bounded scope, severity, disposition, rationale, owner, safe tracking reference, native suppression location, approval date, and expiry date. The allowed exception dispositions SHALL be false positive, accepted risk, or temporary mitigation.

Repository validation SHALL reject an unknown manifest version, duplicate identifier, missing or malformed required field, unsafe absolute suppression path, absent native suppression target, a repository-file target whose resolved path leaves the checkout or resolves to the exception manifest itself, or a suppression target that lacks the exact namespaced marker `security-exception: <id>`. A marker match SHALL end at the identifier boundary so that a short identifier cannot match a longer identifier by prefix. Validation diagnostics SHALL identify a valid exception by its validated identifier and an entry with an invalid identifier by position only; they SHALL NOT echo an invalid raw identifier, a raw YAML source line, or another unvalidated manifest value. The initial manifest MAY contain no exceptions.

#### Scenario: Register a valid exception
- **WHEN** a maintainer records every required field for one narrowly scoped finding and the referenced native suppression contains the exact namespaced marker for the same stable exception identifier
- **THEN** repository validation accepts the exception until its expiry date

#### Scenario: Exception metadata is incomplete
- **WHEN** an exception omits its owner, rationale, safe tracking reference, native suppression location, approval date, or expiry date
- **THEN** repository validation fails with the validated exception identifier and invalid field

#### Scenario: Exception identifier or YAML is malformed
- **WHEN** an exception identifier is invalid or the manifest cannot be parsed as valid YAML
- **THEN** repository validation fails with a static, safe diagnostic that identifies an invalid entry by position where applicable and does not reproduce the invalid value or source line

#### Scenario: Native suppression is not linked
- **WHEN** an exception points to a missing repository file, a target that resolves outside the checkout or to the exception manifest itself, or a native suppression target without the exact namespaced marker for that exception
- **THEN** repository validation fails and does not treat the finding as excepted

#### Scenario: Marker contains another exception identifier
- **WHEN** a native suppression contains a namespaced marker for a longer identifier that merely begins with the exception identifier
- **THEN** repository validation rejects the exception because the marker does not match the complete identifier

### Requirement: Narrow and time-bounded suppression
An exception SHALL use the narrowest scanner-native suppression that covers the identified finding and scope. The manifest SHALL NOT act as the suppression mechanism itself. Disabling a scanner, disabling an entire security gate, or applying a repository-wide wildcard SHALL NOT qualify as an exception and requires a separately approved specification change.

Every exception SHALL have an approval date no later than the validator's current UTC date and SHALL expire no later than 90 calendar days after its approval date. It SHALL become invalid at 00:00 UTC on its expiry date. Resolving a finding SHALL remove both its manifest entry and its native suppression in the same change; extending or changing an exception SHALL require a new review with updated rationale, approval date, and expiry date.

#### Scenario: Exception reaches its expiry date
- **WHEN** repository validation runs at or after 00:00 UTC on an exception's expiry date
- **THEN** validation fails and identifies the expired exception for remediation or renewed review

#### Scenario: Exception exceeds the review window
- **WHEN** an exception's expiry date is more than 90 calendar days after its approval date
- **THEN** repository validation rejects the exception

#### Scenario: Exception approval is future-dated
- **WHEN** an exception's approval date is later than the validator's current UTC date
- **THEN** repository validation rejects the exception as not yet approved

#### Scenario: Finding is remediated
- **WHEN** the underlying finding is fixed
- **THEN** the same change removes the manifest entry and the linked native suppression before verification passes

#### Scenario: Maintainer attempts a blanket bypass
- **WHEN** a change disables a scanner or security gate or uses a repository-wide wildcard instead of a finding-scoped native suppression
- **THEN** the exception contract does not authorize the bypass and the change requires separate OpenSpec review

### Requirement: Secret-specific remediation and bypass handling
A confirmed exposed secret SHALL be revoked or rotated and removed from tracked content; suppressing its detector SHALL NOT count as remediation. A push-protection bypass for an intentional non-secret fixture SHALL use GitHub's recorded bypass reason and SHALL enter the same owned, expiring exception lifecycle. Repository exception metadata, validation output, logs, fixtures, and public tracking SHALL NOT contain the secret value or a sensitive source URL.

#### Scenario: Real credential is detected
- **WHEN** secret scanning or another scanner identifies a confirmed credential in tracked content
- **THEN** the credential is revoked or rotated, the tracked content is remediated, and no exception marks the credential as resolved

#### Scenario: Intentional fixture triggers push protection
- **WHEN** a maintainer must bypass push protection for an intentional non-secret fixture
- **THEN** the bypass has a recorded GitHub reason and a repository exception with an owner, safe tracking reference, bounded scope, and expiry date

### Requirement: Authoritative repository protection verification
GitHub secret scanning and secret-scanning push protection SHALL remain enabled for the repository. Delivery verification for a change that modifies security policy, a scanner, a security gate, an exception, or release-security behavior SHALL perform a read-only authenticated query of the exact target repository on `github.com` and confirm both settings from GitHub's authoritative repository state. A caller-provided GitHub host override SHALL NOT redirect this authoritative query. Cached documentation, an assumed default, or a successful local scan SHALL NOT substitute for this evidence.

Unavailable, unauthorized, malformed, timed-out, or disabled repository-setting evidence SHALL be reported as blocked or failed and SHALL NOT be reported as passed. Hosted response processing SHALL safely reject null, array, or otherwise malformed payloads without a stack trace or raw response content. A push-protection bypass alert SHALL enter the security finding lifecycle and SHALL NOT by itself count as successful protection verification.

#### Scenario: Repository protections are enabled
- **WHEN** an authenticated read-only delivery check reports secret scanning and push protection enabled for the exact target repository
- **THEN** the repository-protection gate passes and records the repository identity without emitting secrets or credentials

#### Scenario: Repository setting cannot be confirmed
- **WHEN** the authoritative query is unavailable, unauthorized, malformed, times out, or reports either protection disabled
- **THEN** delivery of the affected security change remains blocked and the unavailable evidence is not described as passed

#### Scenario: GitHub host override is present
- **WHEN** the delivery environment selects a different default GitHub host
- **THEN** authoritative repository and hosted-dismissal queries still target `github.com`

#### Scenario: Hosted response has an invalid shape
- **WHEN** a repository-setting or hosted-dismissal query returns null, an array, or another unexpected response shape
- **THEN** verification exits safely with blocked or failed status and emits only the repository identity or validated exception identifier needed to locate the failure

#### Scenario: Push protection is bypassed
- **WHEN** GitHub records that a contributor bypassed push protection
- **THEN** the bypass is triaged through the owned security finding lifecycle even if repository-level push protection remains enabled
