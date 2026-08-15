# Media Finder

Media Finder is a self-hosted catalog and torrent-acquisition control plane for manually curated movie and series libraries. It preserves selected metadata revisions, delegates downloads to pluggable clients, and gives external processors stable metadata, naming, and NFO APIs.

The project is being implemented from the approved [`bootstrap-media-finder`](openspec/changes/bootstrap-media-finder/) OpenSpec change.

## Deployment

The production image is published at `ghcr.io/hametovbr/media-finder`. Start with [`compose.example.yaml`](compose.example.yaml), keep its localhost-only port until external authentication is configured, and pin an immutable `vX.Y.Z` image tag for production. Media Finder needs a persistent `/data` volume but no download or media-library mounts.

See the [operations guide](docs/operations.md) for secrets, Komodo or Docker Compose deployment, reverse-proxy authentication, networking, health checks, backups, upgrades, and rollback.

External FileFlows, n8n, and custom post-processors should follow the [processor integration guide](docs/processor-integration.md) for pinned metadata, naming, NFO, expiry, and safe error handling.

## Product boundary

Media Finder owns catalog metadata, user collections, manual release selection, and submission records. It does not scan, mux, move, or monitor media files, and it does not invoke Jellyfin. FileFlows, n8n, or another external processor may consume its APIs after a download client receives a release.

## Development bootstrap

Prerequisites: CPython 3.13, [uv](https://docs.astral.sh/uv/), Node.js 20.19 or newer, and pnpm 11.19.

```console
pnpm install --frozen-lockfile
uv sync --frozen --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
pnpm spec:validate
pnpm spec:list
pnpm docs:check
pnpm delivery:test
pnpm delivery:validate
```

Use the generated OpenSpec skills in `.agents/skills/` and follow [AGENTS.md](AGENTS.md). See [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a change. The interactive low-fidelity [wireframe](docs/design/wireframe.html) records the intended MVP navigation without serving as production UI code.

## License

Media Finder is available under the [MIT License](LICENSE).
