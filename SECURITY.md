# Security policy

## Supported versions

No stable version has been released. Security fixes currently target the default development branch and the next release.

## Reporting a vulnerability

Use GitHub private vulnerability reporting for this repository. Do not open a public issue containing exploit details, credentials, passkeys, private service URLs, or personal media data.

Include the affected revision, impact, reproduction steps, and any suggested mitigation. Maintainers will acknowledge a complete report, coordinate a fix and disclosure timeline, and credit the reporter when requested.

## Finding lifecycle

Every finding from review, secret scanning, static analysis, dependency analysis, filesystem analysis, or image analysis has exactly one current disposition:

- **resolved**: the affected code, dependency, configuration, or artifact has been remediated;
- **unresolved**: an owner and a safe tracking reference identify the remaining work;
- **active exception**: the exact finding and bounded scope have a reviewed, unexpired entry in `.github/security-exceptions.yaml` and a linked scanner-native suppression.

A finding that violates an approved blocking policy blocks the affected change or artifact unless it is resolved or covered by an active exception. Advisory findings remain visible and owned until resolved, reclassified, or explicitly excepted. A safe public issue may track non-sensitive work; use private vulnerability reporting or another access-controlled record for credentials, authenticated URLs, exploit details, raw upstream evidence, or private service locations.

## Security exceptions

`.github/security-exceptions.yaml` is the versioned governance record, not an allowlist consumed by scanners. Each entry identifies the scanner, finding, severity, bounded scope, disposition, rationale, owner, safe tracking reference, approval date, expiry date, and native suppression. Allowed dispositions are `false-positive`, `accepted-risk`, and `temporary-mitigation`.

Use the narrowest scanner-native mechanism. A repository-file suppression must resolve inside the checkout, must not resolve to the exception manifest itself, and must contain the exact namespaced audit marker `security-exception: <id>`. A GitHub code-scanning dismissal must use the exact alert and include the same namespaced marker in its dismissal comment. The identifier match is complete: a marker for a longer identifier does not cover an exception whose ID is only its prefix. Disabling a scanner or gate, or adding a repository-wide wildcard, is not an exception and requires a separately approved OpenSpec change.

An exception's `approved_on` date cannot be later than the validator's current UTC date. An exception expires at 00:00 UTC on `expires_on` and cannot cover more than 90 calendar days from `approved_on`. Renewal requires reviewed changes to the rationale, approval date, and expiry date. Remediation removes both the manifest entry and the linked native suppression in the same change. `pnpm delivery:validate` rejects malformed, unlinked, future-dated, excessive, and expired entries.

Never put credentials, authenticated URLs, raw scanner payloads, exploit instructions, or private service details in the manifest, suppression marker, validation output, fixture, public issue, or pull-request text.

## Secret findings and push protection

A confirmed exposed secret must be revoked or rotated and removed from tracked content. Suppressing a detector does not remediate a real credential. Push-protection bypass is reserved for an intentional non-secret fixture: record GitHub's bypass reason and create the same owned, bounded, expiring security exception. Treat every bypass alert as a finding even while repository-level push protection remains enabled.

## Repository protection verification

For a change that modifies security policy, a scanner, a security gate, an exception, or release-security behavior, query the exact target repository before delivery:

```console
pnpm security:verify -- --repository OWNER/REPOSITORY
```

The command performs read-only authenticated GitHub API requests against `github.com` even when the CLI environment selects another default host. Each request has a 30-second timeout. The command verifies repository identity, secret scanning, push protection, and any GitHub-hosted exception dismissals, and emits only safe state plus validated exception IDs. Exit status `0` is verified, `1` is disabled or invalid evidence, and `2` is unavailable, unauthorized, or timed-out evidence. A non-zero result blocks the security-affecting delivery and must not be reported as passed. This live check is intentionally not an ordinary required pull-request job because that job would need broader repository visibility than its least-privilege token provides.

## Deployment boundary

Media Finder has no user database and trusts authentication performed by an external reverse proxy. Keep the service bound to localhost until that authentication is configured. Supply integration configuration only through the exact environment variables declared by each module manifest. Neither resolved values nor environment-variable references are stored.

Never attach real `.torrent` files, magnet URIs, Prowlarr download URLs, qBittorrent credentials, integration tokens, or database contents to public reports.

Back up the complete `/data` directory before every upgrade. If an upgrade fails after migration begins, restore that backup together with the previous immutable image tag; do not run an older image against a newer schema. See the [operations guide](docs/operations.md) for the supported procedure.
