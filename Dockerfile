# Один процесс: собранный фронт отдаёт FastAPI (см. `npm run build` -> spec_council/static).

FROM node:24-alpine AS ui
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # -> /src/backend/spec_council/static

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
COPY --from=ui /src/backend/spec_council/static ./spec_council/static

RUN useradd --create-home app && chown -R app:app /app
USER app

EXPOSE 8420
CMD ["uvicorn", "spec_council.app:app", "--host", "0.0.0.0", "--port", "8420"]
