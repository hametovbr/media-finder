## ADDED Requirements

### Requirement: Configurable log level
The application SHALL read `MEDIA_FINDER_LOG_LEVEL` once at process construction. It SHALL accept only `debug`, `info`, `warning`, `error`, and `critical` case-insensitively, default to `info`, and fail startup safely for any other value. The selected level SHALL apply to the root logger and to the Uvicorn access and error logs.

#### Scenario: Default log level
- **WHEN** the process starts without `MEDIA_FINDER_LOG_LEVEL`
- **THEN** the application and Uvicorn logs emit at the `info` level

#### Scenario: Select a log level
- **WHEN** the process starts with `MEDIA_FINDER_LOG_LEVEL=debug` in any letter case
- **THEN** `debug` and higher messages appear in the application and Uvicorn logs for the single worker

#### Scenario: Reject an invalid log level
- **WHEN** the process starts with an unsupported `MEDIA_FINDER_LOG_LEVEL` value
- **THEN** startup fails with a safe configuration error before the web server begins accepting requests
