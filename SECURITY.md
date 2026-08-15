# Security policy

## Supported versions

No stable version has been released. Security fixes currently target the default development branch and the next release.

## Reporting a vulnerability

Use GitHub private vulnerability reporting for this repository. Do not open a public issue containing exploit details, credentials, passkeys, private service URLs, or personal media data.

Include the affected revision, impact, reproduction steps, and any suggested mitigation. Maintainers will acknowledge a complete report, coordinate a fix and disclosure timeline, and credit the reporter when requested.

## Deployment boundary

Media Finder has no user database and trusts authentication performed by an external reverse proxy. Keep the service bound to localhost until that authentication is configured. Supply secrets only through environment variables and use `env:VARIABLE_NAME` references in stored configuration.

Never attach real `.torrent` files, magnet URIs, Prowlarr download URLs, qBittorrent credentials, integration tokens, or database contents to public reports.
