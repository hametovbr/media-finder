# Operations guide

Media Finder runs as one non-root application container with SQLite state under `/data`. It does not need access to download or media directories. Keep the service bound to localhost until an authenticating reverse proxy is in place.

## Image tags

Use an immutable `vX.Y.Z` tag for production deployments. Moving tags are provided for convenience but make rollback provenance less explicit.

| Tag | Meaning |
| --- | --- |
| `v1.2.3` | Immutable stable release |
| `1.2` | Latest stable patch in the minor line |
| `latest` | Latest stable GitHub Release after full verification |
| `edge` | Current fully verified `main` commit; not a stable release |

Images are published for `linux/amd64` and `linux/arm64`.

Both publishing paths run the same documentation, OpenSpec, format, lint, type, unit, integration, contract, browser, and production-image checks for the exact commit before granting the publish job package-write permission. A failed or skipped verification cannot publish `edge` or stable tags.

## Initial deployment

Copy [`compose.example.yaml`](../compose.example.yaml) and supply the two required runtime secrets through the environment or the secret store of the orchestrator. Do not commit their values.

```console
export MEDIA_FINDER_UI_SECRET="$(openssl rand -hex 32)"
export MEDIA_FINDER_INTEGRATION_TOKEN="$(openssl rand -hex 32)"
docker compose -f compose.example.yaml up -d
curl --fail http://127.0.0.1:8080/health/ready
```

The container runs migrations before it starts the single Uvicorn worker. A migration or database-access failure terminates the container instead of serving against an unknown schema. Liveness is available at `/health/live`; readiness checks the database and current migration head at `/health/ready`. Neither endpoint depends on TMDB, Prowlarr, or a download client.

When deploying from a Git-backed stack in an orchestrator such as Komodo, keep `compose.example.yaml` unchanged in the repository or copy it into an infrastructure repository. Define secrets in the orchestrator environment, select an immutable image tag, and apply network or proxy overrides at deployment time.

## Runtime configuration

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `MEDIA_FINDER_UI_SECRET` | Yes | None | Signs UI sessions and CSRF state; use at least 32 random bytes |
| `MEDIA_FINDER_INTEGRATION_TOKEN` | Yes | None | Bearer token for processor-facing `/api/v1` endpoints |
| `MEDIA_FINDER_DATABASE_URL` | No | `sqlite:////data/media-finder.db` | SQLite URL inside the persistent data directory |
| `MEDIA_FINDER_SECURE_COOKIE` | No | `true` in the image; `false` in the localhost Compose example | Enables the cookie `Secure` attribute; set `true` behind HTTPS |
| `MEDIA_FINDER_PORT` | Compose only | `8080` | Local host port in the example |
| `MEDIA_FINDER_IMAGE_TAG` | Compose only | `latest` | GHCR tag; pin `vX.Y.Z` for production |

Provider and download-client credentials use operator-chosen environment variables. Store the corresponding `env:VARIABLE_NAME` reference in the Settings UI, never the secret value. For example:

```yaml
environment:
  TMDB_TOKEN: ${TMDB_TOKEN:?set the TMDB bearer token}
  PROWLARR_API_KEY: ${PROWLARR_API_KEY:?set the Prowlarr API key}
  QBITTORRENT_USERNAME: ${QBITTORRENT_USERNAME:?set the qBittorrent username}
  QBITTORRENT_PASSWORD: ${QBITTORRENT_PASSWORD:?set the qBittorrent password}
```

The matching settings values are `env:TMDB_TOKEN`, `env:PROWLARR_API_KEY`, `env:QBITTORRENT_USERNAME`, and `env:QBITTORRENT_PASSWORD`. Restart the container after adding or rotating an environment secret so the process receives the new value.

## Network exposure and external authentication

Media Finder deliberately has no user database. Every UI route must be protected by an external authentication layer before it is published to a LAN or the internet. Keep the example's `127.0.0.1` bind for a reverse proxy running on the host. The proxy should:

- authenticate every UI request;
- terminate HTTPS and forward the original scheme and host;
- preserve request IDs when present;
- apply its own access policy to `/health/*` if those endpoints are exposed;
- require the Media Finder Bearer token in addition to any proxy policy for `/api/v1/*`.

Set `MEDIA_FINDER_SECURE_COOKIE=true` after HTTPS is active. Do not rely on the Bearer token as UI authentication.

For a proxy running in Docker, an override may remove the published port and join a user-selected external network:

```yaml
services:
  media-finder:
    ports: []
    networks:
      - proxy
    environment:
      MEDIA_FINDER_SECURE_COOKIE: "true"

networks:
  proxy:
    external: true
    name: ${PROXY_NETWORK_NAME:?set the existing proxy network}
```

The base example intentionally contains no proxy labels, authentication-provider configuration, private domain, or private network name.

## Port and storage customization

Change the localhost port without editing Compose:

```console
MEDIA_FINDER_PORT=9080 docker compose -f compose.example.yaml up -d
```

To use a bind mount, replace the named-volume entry with an absolute host path and make the directory writable by UID/GID `10001`:

```yaml
services:
  media-finder:
    volumes:
      - /srv/media-finder/data:/data
```

Do not mount download or media-library paths. External processors consume the HTTP APIs and own all filesystem operations.

## Backup before every upgrade

`/data` contains the database and SQLite WAL files and is the only mutable application state. Stop the application before copying it so the database, WAL, and shared-memory files form one recoverable snapshot.

The example assigns the stable volume name `media-finder-data`:

```console
docker compose -f compose.example.yaml stop media-finder
docker run --rm --volume media-finder-data:/data:ro --volume "$PWD:/backup" busybox:1.36 \
  tar -C /data -czf /backup/media-finder-data-before-upgrade.tar.gz .
docker compose -f compose.example.yaml start media-finder
```

Store the archive outside the Docker host and verify that it can be listed with `tar -tzf`. For a bind mount, use the host backup system to snapshot the entire configured directory while the container is stopped.

## Upgrade

1. Record the currently deployed immutable image tag.
2. Back up `/data` using the procedure above.
3. Change `MEDIA_FINDER_IMAGE_TAG` to the new immutable `vX.Y.Z` tag.
4. Pull and recreate the service.
5. Wait for readiness and inspect startup logs.

```console
docker compose -f compose.example.yaml pull media-finder
docker compose -f compose.example.yaml up -d media-finder
docker compose -f compose.example.yaml ps
curl --fail http://127.0.0.1:${MEDIA_FINDER_PORT:-8080}/health/ready
```

If migrations fail, the web server will not start. Do not bypass the entrypoint or run the new application against the old schema.

## Rollback

Rollback means restoring both the previous immutable image and the pre-upgrade `/data` snapshot. Merely changing the image tag is unsafe after a schema migration.

1. Stop the service.
2. Verify the exact volume or bind-mount target before changing any files.
3. Move the failed volume aside or create a fresh empty `media-finder-data` volume.
4. Restore the complete archive into the empty target.
5. Set the previous `vX.Y.Z` image tag and start the service.
6. Confirm `/health/ready` before reopening traffic.

Retain the failed data separately until the rollback is verified. Never restore into a running container.

## Local image validation

The same production image used by releases can be built locally:

```console
docker build --tag media-finder:local .
```

Repository delivery contracts can be checked without Docker using `pnpm delivery:validate`. GitHub Actions performs a real production-image build on every pull request and `main` update.
