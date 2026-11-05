# syntax=docker/dockerfile:1.7
#
# One image: FastAPI + the built React app + the local embedding and reranker models.
#   docker compose up            (see compose.yaml; needs OPENAI_API_KEY in .env)
# Data (the cloned corpus, its index, saved runs) lives in the /data volume.

# ---- web: build the React app ----------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /app/web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# ---- app: Python API, serving the web build --------------------------------------------------
FROM python:3.13-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/
# git: the git_history tool reads the corpus history, and `acr setup` clones the corpus.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 acr \
 && mkdir -p /data /opt/models \
 && chown acr:acr /data /opt/models

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    ACR_DATA_DIR=/data \
    ACR_MODELS_PATH=/opt/models \
    PYTHONUNBUFFERED=1

WORKDIR /app
# Dependencies first, so source changes don't reinstall them.
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN cd backend && uv sync --locked --no-dev --no-install-project
COPY backend/src ./backend/src
COPY corpora.toml ./
COPY eval ./eval
RUN cd backend && uv sync --locked --no-dev
COPY --from=web /app/web/dist ./web/dist
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

USER acr
# Bake the models in (~150 MB) so the first question doesn't wait for a download.
RUN acr models fetch

EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=4)"
ENTRYPOINT ["docker-entrypoint.sh"]
