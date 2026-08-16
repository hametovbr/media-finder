# Security policy

## Supported versions

No stable version has been released. Security fixes currently target the default development branch and the next release.

## Reporting a vulnerability

Use GitHub private vulnerability reporting for this repository. Do not open a public issue containing exploit details, credentials, passkeys, private service URLs, or personal media data.

Include the affected revision, impact, reproduction steps, and any suggested mitigation. Maintainers will acknowledge a complete report, coordinate a fix and disclosure timeline, and credit the reporter when requested.

## Deployment boundary

Media Finder has no user database and trusts authentication performed by an external reverse proxy. Keep the service bound to localhost until that authentication is configured. Supply integration configuration only through the exact environment variables declared by each module manifest. Neither resolved values nor environment-variable references are stored.

Never attach real `.torrent` files, magnet URIs, Prowlarr download URLs, qBittorrent credentials, integration tokens, or database contents to public reports.

Back up the complete `/data` directory before every upgrade. If an upgrade fails after migration begins, restore that backup together with the previous immutable image tag; do not run an older image against a newer schema. See the [operations guide](docs/operations.md) for the supported procedure.
