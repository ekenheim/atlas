# syntax=docker/dockerfile:1
# One image for both roles: `atlas api` (default) or `atlas worker`.

FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.7.3 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ backend/
RUN uv sync --frozen --no-dev
# Versioned config (the company universe), read relative to WORKDIR /app.
COPY configs/ configs/
COPY --from=frontend /build/out /app/frontend

RUN useradd --system --uid 10001 --no-create-home atlas \
    && mkdir -p /data/archive && chown 10001 /data/archive
USER 10001
ENV PATH="/app/.venv/bin:$PATH" \
    ATLAS_FRONTEND_DIR=/app/frontend
EXPOSE 8000
ENTRYPOINT ["atlas"]
CMD ["api"]
