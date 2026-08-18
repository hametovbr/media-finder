## 1. Configuration parsing

- [x] 1.1 Add focused failing tests for default `info`, valid case-insensitive values, and an invalid `MEDIA_FINDER_LOG_LEVEL` producing a `ConfigurationError` with `safe_details == {"variable": "MEDIA_FINDER_LOG_LEVEL"}`; observe RED.
- [x] 1.2 Add `log_level` to `CoreConfiguration` with `DEFAULT_LOG_LEVEL` and `ALLOWED_LOG_LEVELS`, parse and validate `MEDIA_FINDER_LOG_LEVEL` in `from_environment`, and make the focused tests GREEN.

## 2. Logging configuration and startup wiring

- [x] 2.1 Add focused failing tests for `configure_logging` setting the root logger level and for `run()` passing `log_level` to `uvicorn.run`; observe RED.
- [x] 2.2 Add `LOG_FORMAT` and `configure_logging` to `runtime.py`, call it first in `run()`, and pass `log_level` to `uvicorn.run`; update `test_run_migrates_before_starting_exactly_one_worker` expectations and make tests GREEN.

## 3. Documentation and deployment

- [x] 3.1 Add the `MEDIA_FINDER_LOG_LEVEL` row to the runtime configuration table in `docs/operations.md`.
- [x] 3.2 Add `MEDIA_FINDER_LOG_LEVEL: ${MEDIA_FINDER_LOG_LEVEL:-info}` to the Compose example environment block.

## 4. Verification

- [x] 4.1 Run `pnpm spec:validate` and the Python format, lint, type, and test gates; confirm no regressions and a clean `git diff --check`.
