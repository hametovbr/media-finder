## Why

Media Finder already accepts private vulnerability reports and has repository secret scanning and push protection enabled, but it has no enforceable repository contract for triaging findings, owning exceptions, expiring suppressions, or verifying that repository-level protection remains enabled. This governance foundation is needed before additional SAST and supply-chain scanners can become required without accumulating anonymous or permanent bypasses.

## What Changes

- Define a repository-owned lifecycle for detected security findings from triage through remediation or a time-bounded exception.
- Add a versioned, machine-validated security-exception manifest with stable finding identity, severity, disposition, rationale, owner, safe tracking reference, native suppression locator, approval date, and expiry date.
- Require every suppression to use the scanner's native narrow mechanism, link back to one manifest entry, expire within 90 days, and fail repository validation once expired or structurally invalid.
- Define secret-specific handling that never records credentials or sensitive URLs and treats rotation/revocation as remediation rather than suppression.
- Define a read-only delivery check that verifies GitHub secret scanning and push protection remain enabled and treats unavailable or disabled repository evidence as blocking rather than passed.
- Extend the existing security policy and delivery validation tests instead of introducing a security service, cross-tool scanner framework, or runtime component.
- Explicitly defer Ruff security-rule selection, CodeQL setup, Trivy scanning, dependency automation, artifact promotion, and changes to required check contexts to their own OpenSpec changes.
- Preserve the catalog-and-acquisition product boundary; no runtime, UI, API, persistence, module, authentication, network-exposure, or About/Credits capability changes are introduced.

## Capabilities

### New Capabilities

- `security-finding-governance`: Repository policy, exception metadata, expiry enforcement, secret-safe handling, and GitHub push-protection verification for security findings.

### Modified Capabilities

None.

## Impact

The change affects `SECURITY.md`, a repository-owned security-exception manifest, the existing delivery validator and its tests, and contributor-facing verification commands. It adds no production dependency, runtime process, public API, stored schema, module contract, environment variable, or GitHub Actions check context. Repository security settings are read and verified but are not mutated by this change.
