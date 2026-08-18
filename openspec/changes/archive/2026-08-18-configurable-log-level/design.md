## Context

The server is started by `run()` in `apps/server/src/media_finder_server/runtime.py`, which calls `uvicorn.run(application, host="0.0.0.0", port=8000, workers=1, proxy_headers=True)` without `log_level` or `log_config`. Core configuration is a frozen dataclass `CoreConfiguration` built by `from_environment` from `os.environ`, using the `MEDIA_FINDER_*` prefix and failing safely through `ConfigurationError` for invalid values. See `proposal.md` for motivation.

## Goals / Non-Goals

**Goals:**

- Parse and validate `MEDIA_FINDER_LOG_LEVEL` exactly once at process construction, in the same strict style as `MEDIA_FINDER_UI_MODE`.
- Apply one log level to the root logger and to Uvicorn's `error`/`access`/`asgi` loggers.
- Keep log output plain text with no new runtime dependencies.

**Non-Goals:**

- No JSON or structured logging.
- No per-module or per-endpoint log levels.
- No exposure of the log level through any HTTP endpoint.

## Decisions

### Decision 1: `MEDIA_FINDER_LOG_LEVEL` with a closed, case-insensitive value set

Add a `log_level: str` field to `CoreConfiguration`. In `from_environment`, read `MEDIA_FINDER_LOG_LEVEL`, default to `info`, strip and lowercase it, and accept only `debug`, `info`, `warning`, `error`, and `critical`; otherwise raise `_invalid("MEDIA_FINDER_LOG_LEVEL")`.

- **Why**: mirrors the existing `MEDIA_FINDER_UI_MODE` contract (read once, closed set, safe-fail) and keeps validation in core where every other core environment value is validated.
- **Alternatives considered**: validating in the server host only (splits configuration ownership); accepting arbitrary strings and deferring failure to `logging` (loses the safe, message-safe startup error).

### Decision 2: Configure the root logger explicitly, then pass `log_level` to Uvicorn

Add a `configure_logging(log_level: str)` helper in `runtime.py` that maps the validated name to a numeric level with `getattr(logging, log_level.upper(), None)`, guards the result with `isinstance(..., int)`, sets the level on the root logger, and adds a single stderr `StreamHandler` with `LOG_FORMAT` only when the root has no handlers. `run()` calls this helper first, before `migrate_to_head`, and adds `log_level=configuration.log_level` to `uvicorn.run(...)`.

- **Why**: the root logger governs application loggers such as `media_finder_server.runtime`, while Uvicorn's `log_level` argument governs its `error`, `access`, and `asgi` loggers. Together they produce one consistent level without a bespoke `dictConfig`. Setting the root level explicitly (rather than relying on `logging.basicConfig`, which only sets the level when the root has no handlers yet) keeps the behavior deterministic regardless of prior handler state. Configuring before migrations means migration errors are already logged at the selected level.
- **Alternatives considered**: a full `dictConfig` passed as Uvicorn's `log_config` (more control, but more surface area and risk around Uvicorn's `TRACE` level and formatter injection); `logging.basicConfig(level=...)` alone (fails to change the level once a handler already exists); setting only Uvicorn's level and leaving the root logger untouched (application logs would stay at the default `WARNING`, contradicting the goal).

### Decision 3: Keep the default in code and in the Compose example only

Add `MEDIA_FINDER_LOG_LEVEL: ${MEDIA_FINDER_LOG_LEVEL:-info}` to `compose.example.yaml` and a row to `docs/operations.md`. Do not add a duplicate `ENV` default to the `Dockerfile`.

- **Why**: the code default (`info`) is the single source of truth; the Compose placeholder documents the customization point for operators, matching the `MEDIA_FINDER_UI_MODE` precedent.

## Risks / Trade-offs

- [A future change to structured logs would rework this config surface] → accepted; structured logging is explicitly out of scope and can layer on top of the same environment contract later.
- [`logging.basicConfig` format differs slightly from Uvicorn's `levelprefix` format] → acceptable for plain-text logs; both still carry timestamp, level, and logger name.
- [Raising the level to `debug` increases log volume, including from libraries] → mitigated by the operator explicitly opting in and by keeping the default at `info`.

## Migration Plan

1. Deploy the new image; existing deployments without `MEDIA_FINDER_LOG_LEVEL` continue to log at `info`.
2. To troubleshoot, set `MEDIA_FINDER_LOG_LEVEL=debug` and recreate the container.
3. Rollback is a configuration-only change: unset the variable or set it back to `info` and recreate the container. No database migration or data change is involved.

## Open Questions

None.
