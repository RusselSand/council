# Один процесс: собранный фронт отдаёт FastAPI. Фронт собирается у себя, сюда его кладёт COPY.

FROM node:24-alpine AS ui
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # -> /src/frontend/dist

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# git нужен uv, чтобы забрать зависимость agent-workers из GitHub.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./
# agent-workers — приватный репо: токен приходит build secret'ом, как в backend/Dockerfile.
RUN --mount=type=secret,id=agent_workers_token \
    test -s /run/secrets/agent_workers_token \
    || { echo "Нет токена agent-workers: впишите AGENT_WORKERS_TOKEN в .env" \
              "рядом с docker-compose.yml (образец — .env.example)" >&2; exit 1; } \
    && GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0="url.https://x-access-token:$(cat /run/secrets/agent_workers_token)@github.com/RusselSand/agent-workers.insteadOf" \
    GIT_CONFIG_VALUE_0="https://github.com/RusselSand/agent-workers" \
    uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
COPY --from=ui /src/frontend/dist ./spec_council/static

RUN useradd --create-home app && chown -R app:app /app
USER app

EXPOSE 8420
CMD ["uvicorn", "spec_council.app:app", "--host", "0.0.0.0", "--port", "8420"]
