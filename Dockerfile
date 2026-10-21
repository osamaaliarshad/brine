# brine: the web UI and the backend in one image.
#
#   docker run -d -p 8000:8000 \
#     -v ./config.yaml:/config/config.yaml:ro -v brine-data:/data \
#     ghcr.io/osamaaliarshad/brine:latest
#
# Or use docker-compose.yml. The database (SQLite by default) lives in /data.

FROM node:24-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.27 /uv /usr/local/bin/uv

ARG BRINE_VERSION=dev
ENV BRINE_VERSION=${BRINE_VERSION} \
    BRINE_CONFIG=/config/config.yaml \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra postgres
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
COPY --from=frontend /src/frontend/dist /app/frontend/dist

# brine's default database is data/brine.db, next to the app: point that at the /data volume.
RUN useradd --system --uid 10001 --no-create-home brine \
    && mkdir -p /data /config \
    && chown brine /data \
    && ln -s /data /app/backend/data
USER brine
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/healthz', timeout=4)"

# Behind a reverse proxy, set FORWARDED_ALLOW_IPS to its address so brine trusts its headers.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
