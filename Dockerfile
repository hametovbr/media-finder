# syntax=docker/dockerfile:1.7

FROM python:3.13.14-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build

COPY pyproject.toml uv.lock README.md ./
COPY apps/server/pyproject.toml apps/server/pyproject.toml
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/module-sdk/pyproject.toml packages/module-sdk/pyproject.toml
COPY packages/control-contracts/pyproject.toml packages/control-contracts/pyproject.toml
COPY packages/builtin-ui/pyproject.toml packages/builtin-ui/pyproject.toml
COPY packages/modules/metadata-manual/pyproject.toml packages/modules/metadata-manual/pyproject.toml
COPY packages/modules/metadata-tmdb/pyproject.toml packages/modules/metadata-tmdb/pyproject.toml
COPY packages/modules/release-prowlarr/pyproject.toml packages/modules/release-prowlarr/pyproject.toml
COPY packages/modules/download-qbittorrent/pyproject.toml packages/modules/download-qbittorrent/pyproject.toml
COPY apps/server/src ./apps/server/src
COPY packages/core/src ./packages/core/src
COPY packages/module-sdk/src ./packages/module-sdk/src
COPY packages/control-contracts/src ./packages/control-contracts/src
COPY packages/builtin-ui/src ./packages/builtin-ui/src
COPY packages/modules/metadata-manual/src ./packages/modules/metadata-manual/src
COPY packages/modules/metadata-tmdb/src ./packages/modules/metadata-tmdb/src
COPY packages/modules/release-prowlarr/src ./packages/modules/release-prowlarr/src
COPY packages/modules/download-qbittorrent/src ./packages/modules/download-qbittorrent/src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13.14-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MEDIA_FINDER_DATABASE_URL=sqlite:////data/media-finder.db

RUN groupadd --gid 10001 media-finder \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin media-finder \
    && mkdir --parents /app /data \
    && chown --recursive 10001:10001 /app /data

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 alembic ./alembic
COPY --chown=10001:10001 alembic.ini ./alembic.ini

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).close()"]
ENTRYPOINT ["python", "-m", "media_finder_server"]
