# syntax=docker/dockerfile:1.7

FROM python:3.13.14-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.13.14-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MEDIA_FINDER_DATABASE_URL=sqlite:////data/media-finder.db

RUN groupadd --gid 10001 media-finder \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin media-finder \
    && mkdir --parents /app /data \
    && chown --recursive 10001:10001 /app /data

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 src ./src
COPY --chown=10001:10001 alembic ./alembic
COPY --chown=10001:10001 alembic.ini ./alembic.ini

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).close()"]
ENTRYPOINT ["python", "-m", "media_finder.runtime"]
