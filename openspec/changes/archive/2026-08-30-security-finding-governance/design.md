## Context

See `proposal.md` for motivation and `specs/security-finding-governance/spec.md` for the behavior contract. The current repository already has a concise `SECURITY.md`, an extensible `scripts/validate-delivery.mjs` with Node test fixtures, the `yaml` parser in root tooling dependencies, and GitHub CLI in the publication workflow. At planning time on 2026-08-28, GitHub's authoritative repository response reported secret scanning and push protection enabled, while CodeQL default setup was not configured. GitHub settings are mutable external state, so that observation is baseline evidence rather than a permanent guarantee.

The governance model must support both repository-file suppressions, such as a narrow linter or scanner ignore, and GitHub-hosted alert dismissals, such as a future CodeQL exception. It must not put credentials, authenticated URLs, raw findings, or private advisory content into the public repository.

## Goals / Non-Goals

**Goals:**

- Give future scanners one small, tool-independent metadata contract for ownership, rationale, review, and expiry while leaving actual suppression to each scanner's native mechanism.
- Make structural and expiry failures deterministic in the existing local and CI validation path.
- Make mutable GitHub protection state and GitHub-hosted suppressions explicitly verifiable at delivery time without granting a required pull-request job administrative repository access.
- Keep the mechanism usable from a clean checkout with repository-local tooling.

**Non-Goals:**

- Selecting scanner severities or blocking thresholds.
- Installing or configuring Ruff security rules, CodeQL, Trivy, Dependabot/Renovate policy, artifact scanning, or image promotion.
- Building a vulnerability database, dashboard, webhook receiver, issue synchronizer, or generic scanner abstraction.
- Changing GitHub settings, required check names, runtime code, product data, public APIs, modules, or deployment topology.

## Decisions

### 1. Store only exception metadata in `.github/security-exceptions.yaml`

The checked-in document will use this shape:

```yaml
schema_version: 1
exceptions: []
```

An entry will contain `id`, `scanner`, `finding_id`, `severity`, `scope`, `disposition`, `rationale`, `owner`, `tracking_ref`, `approved_on`, `expires_on`, and a `suppression` object. Dates use `YYYY-MM-DD`; severity is one of `critical`, `high`, `medium`, `low`, or `unknown`; disposition is one of `false-positive`, `accepted-risk`, or `temporary-mitigation`. Free-text fields are bounded non-empty strings, and tracking references must be safe repository, issue, advisory, or alert identifiers rather than finding evidence. Parser and validation failures use static messages: a validated exception ID may label its error, but an invalid ID is represented only by its array position. Raw YAML parser text, source lines, invalid field values, and unvalidated manifest fragments are never emitted.

This is a configuration-rung solution. The manifest records governance metadata but does not suppress a finding. A shared allowlist that scanners consume directly was rejected because it would duplicate native policy, create a cross-tool compatibility layer, and make the registry itself a bypass engine. Scattered comments without a manifest were rejected because ownership and expiry could not be validated consistently.

### 2. Use typed native-suppression locators

The `suppression` object will use one of two forms:

- `kind: repository-file` with a repository-relative `path`; the target must exist, resolve inside the checkout, not resolve to `.github/security-exceptions.yaml` itself, and contain the exact namespaced marker `security-exception: <id>` as a nearby audit marker.
- `kind: github-code-scanning-alert` with an exact HTTPS alert URL for the target repository; the authenticated delivery check must confirm that the alert remains dismissed and that its dismissal comment contains the same exact namespaced marker.

The marker is matched as a complete token: the identifier portion must end at a non-identifier boundary or end of input, where identifier characters are the manifest's lowercase letters, digits, and hyphens. This permits scanner-native comments around the marker while preventing a short ID from matching the prefix of another exception ID. Repository-file containment and the self-reference prohibition are evaluated on resolved paths, so an in-checkout symlink cannot turn the manifest into its own suppression target.

The local validator will reject unknown kinds. Future scanners that need another hosted suppression kind must update this capability through OpenSpec rather than weakening validation with an arbitrary URL. A generic URL locator was rejected because it could conceal sensitive upstream endpoints and would provide no deterministic verification semantics.

### 3. Extend offline delivery validation and add one narrow live adapter

`scripts/validate-delivery.mjs` will load and validate the manifest as part of the existing `pnpm delivery:validate` gate. Its exported validation entry point will accept an injectable current date so expiry tests remain deterministic; the command-line path will use the current UTC date. Tests will cover the empty baseline, every required field, enums, duplicate IDs, path traversal, missing files, missing audit markers, invalid date order, the 90-day maximum, and expiry.

A small repository-local command, exposed as `pnpm security:verify -- --repository OWNER/REPO`, will invoke `gh api --hostname github.com` without a shell, inspect only the minimum response fields, and return a non-zero status when secret scanning or push protection is unavailable or disabled. The explicit hostname prevents `GH_HOST` or other CLI defaults from redirecting authoritative evidence to a different host. Each subprocess has a 30-second timeout; timeout is unavailable evidence and uses the blocked exit status. If the manifest contains GitHub-hosted suppressions, the command will query only their exact alert endpoints and validate state plus the exact namespaced dismissal marker. Before reading fields, it will require a non-null, non-array JSON object. Output will contain repository identity, boolean states, and validated exception IDs only; it will never print tokens, request headers, alert messages, locations, raw API payloads, or subprocess diagnostics.

The live check remains a delivery-time gate for security-affecting changes rather than a required pull-request workflow job. A PR job may not have permission to observe administrative security settings, and granting it broader credentials would violate least privilege. Documentation-only manual inspection was rejected because it cannot produce an unambiguous exit status. A new service or GitHub App was rejected as unnecessary.

### 4. Treat expiry as an automatic loss of authorization

All exceptions use UTC calendar dates, require `approved_on` to be no later than the validator's current UTC date, and may cover at most 90 days from `approved_on`; an exception is invalid from 00:00 UTC on `expires_on`. Renewal edits both dates and rationale through normal review. Remediation removes both the manifest entry and native suppression in one change.

This intentionally causes an otherwise unchanged branch to fail after an exception expires. That failure is the control, not clock-dependent flakiness. Injectable time keeps unit tests stable, while CI uses the actual date so an expired risk cannot remain silently accepted. Permanent exceptions were rejected because even false positives can change when code, rules, or scanner versions change.

### 5. Keep sensitive evidence outside the repository

`SECURITY.md` will define triage states, ownership, safe tracking, suppression review, expiry, live repository verification, and secret-specific response. A public issue may be used only when its content is safe; private vulnerability reporting or another access-controlled record owns sensitive evidence. The manifest stores identifiers and rationale sufficient for review but no credential, authenticated URL, raw scanner payload, exploit instructions, or private service location.

The repository and maintainers own governance. Individual scanners own detection and their native suppressions. The application runtime, core, modules, built-in UI, and persistence layer receive no security-governance object and read no new environment variable.

### 6. Let each scanner change define its own gate policy

This change defines how findings and exceptions are governed, not which severities block. `python-local-security-rules`, `codeql-primary-sast`, and `supply-chain-scan` must each specify their exact finding classes, thresholds, native suppression surface, and required-check placement. They must integrate with this manifest and live verification contract rather than create parallel exception formats.

This sequencing prevents a governance proposal from pre-approving scanner configuration that has not yet been designed or reviewed.

### 7. Subtraction pass

The final design adds one empty YAML configuration file, validation within an existing script and test suite, one narrow read-only GitHub adapter, and policy prose. It adds zero runtime components, production dependencies, databases, processes, services, scheduled jobs, network listeners, scanner frameworks, or GitHub setting mutations. Removing the live adapter would make authoritative external-state failure non-executable; removing the manifest would make expiry and ownership unenforceable. All larger alternatives are therefore excluded.

## Risks / Trade-offs

- **[Risk] GitHub API visibility depends on maintainer authorization.** → Treat unavailable or unauthorized evidence as blocked, document the minimum read-only command, and do not broaden CI credentials.
- **[Risk] A manifest entry can drift from or accidentally match a different repository-file suppression.** → Require the exact namespaced marker with a complete identifier boundary, resolve the target before containment and self-reference checks, and validate target existence and marker presence.
- **[Risk] A hosted alert can change after local validation.** → Re-query its exact endpoint during security-affecting delivery and bind the result to the target repository.
- **[Risk] Environment-selected GitHub hosts, stalled CLI processes, or malformed payloads can make external evidence ambiguous.** → Pin `github.com`, enforce a finite timeout, validate response shape before field access, and classify these cases as unavailable rather than passed.
- **[Risk] Parser or validation diagnostics can disclose untrusted manifest text.** → Use static diagnostics and positional labels until an exception identifier is validated.
- **[Risk] Public rationale or tracking text can leak sensitive details.** → Bound the repository fields to safe metadata and keep evidence in private reporting or advisory channels.
- **[Risk] A fixed 90-day window adds recurring maintenance.** → Make expiry deterministic and visible; renewal remains an explicit reviewed decision rather than silent permanence.
- **[Risk] The initial empty manifest proves structure but not every future scanner integration.** → Require each later scanner change to add RED/GREEN tests for its native suppression form and blocking policy.

## Migration Plan

1. Add the empty version-1 manifest and focused failing validator tests before validator implementation.
2. Implement deterministic manifest validation and make the current empty baseline pass.
3. Add focused failing tests for disabled, unavailable, and enabled GitHub protection responses, then implement the read-only adapter.
4. Expand `SECURITY.md` and contributor commands with the lifecycle and safe usage procedure.
5. Run the live check against the exact repository and record only safe enabled/disabled evidence in the apply handoff.
6. Run focused, delivery, documentation, and strict OpenSpec validation.
7. Add adversarial RED tests for exact marker binding, resolved self-reference, future approval dates, diagnostic redaction, explicit GitHub hostname selection, malformed hosted payloads, and timeout handling; implement only the minimum hardening needed to make them GREEN.
8. Repeat the focused and repository-wide gates, then obtain an independent review of the hardened exact candidate before synchronization and archive.

Because the initial manifest is empty and no scanner or runtime is changed, rollback removes the manifest, adapter, validator integration, tests, and policy additions together. Once later changes create active exceptions, rollback of this governance capability requires resolving those findings or migrating them to an equally enforceable approved contract first; deleting the registry alone is not a safe rollback.
