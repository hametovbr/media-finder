## Why

Media Finder currently logs with Python's default root logger level and Uvicorn's built-in defaults. There is no operator-facing way to raise or lower log verbosity without rebuilding the image, which makes diagnosing a deployment harder than it should be. Operators need a process-wide log level selectable through the environment when running the container.

## What Changes

- Add a process-wide `MEDIA_FINDER_LOG_LEVEL` environment variable read once at process construction.
- Accept `debug`, `info`, `warning`, `error`, and `critical` case-insensitively, default to `info`, and fail startup safely for any other value.
- Apply the selected level to the root logger and to the Uvicorn access and error logs in the single worker.
- Document the variable in the operator runtime-configuration table and expose it as an explicit placeholder in the generic Compose example.
- No database migration, no new dependency, and no change to stored data or public HTTP contracts.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-and-delivery`: Add a requirement that the runtime reads `MEDIA_FINDER_LOG_LEVEL` once, validates it against a closed set, defaults to `info`, fails safely on invalid values, and applies the level to application and Uvicorn logs.

## Impact

- `packages/core/src/media_finder_core/platform/configuration.py`: `CoreConfiguration` gains a `log_level` field parsed and validated in `from_environment`.
- `apps/server/src/media_finder_server/runtime.py`: a `configure_logging` helper configures the root logger, and `run()` passes the level to `uvicorn.run`.
- `tests/test_runtime.py` and a new logging test module: cover defaults, validation, and the `uvicorn.run` call.
- `docs/operations.md` and `compose.example.yaml`: document and expose the variable.
- No changes to the browser control API, processor API, health endpoints, storage schema, module contracts, or external integration variables.
