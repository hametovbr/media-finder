# Agent instructions

- Write repository documentation and developer-facing prose in English. Russian is limited to localization catalogs, localization tests, and user metadata fixtures.
- Treat `openspec/` as the source of truth for behavior, UX, architecture, APIs, schemas, and module contracts. Do not begin significant implementation until its OpenSpec change is approved.
- Use OpenSpec for behavior, UX, architecture, API, schema, and module-contract changes. Typos, comments, and safe maintenance may be changed directly.
- Never edit generated `.agents/skills/openspec-*` files manually; regenerate them with the pinned OpenSpec CLI.
- Use `adding-metadata-provider`, `adding-download-client`, or `evolving-metadata-schema` before changing the corresponding contract. Update contracts, conformance tests, and fixtures with behavior.
- Keep Media Finder a catalog and acquisition control plane. It does not scan, mux, move, or monitor media files and does not invoke Jellyfin.
- Keep secrets in environment variables, persist only `env:NAME` references, and redact secrets and sensitive URLs from errors and logs.
- Before handoff, run `pnpm spec:validate` plus the format, lint, type, test, and production-build commands documented for the current project stage.
