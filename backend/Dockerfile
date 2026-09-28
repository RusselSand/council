# Бек для разработки: зависимости живут в образе, код приезжает bind-mount'ом.
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# git нужен uv, чтобы забрать зависимость agent-workers из GitHub.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Венв вне /app: иначе его затрёт bind-mount с кодом хоста (там .venv под Windows).
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Отдельный слой: правки кода не пересобирают зависимости.
# --no-install-project — сам пакет придёт из монтирования, PYTHONPATH его найдёт.
COPY pyproject.toml uv.lock ./
# agent-workers — приватный репо. Токен только на чтение приходит build secret'ом
# agent_workers_token (см. docker-compose.yml), а не ARG: ARG остаётся в истории образа.
# Подмена адреса живёт только в окружении этой команды, в образ токен не попадает.
RUN --mount=type=secret,id=agent_workers_token \
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0="url.https://x-access-token:$(cat /run/secrets/agent_workers_token)@github.com/RusselSand/agent-workers.insteadOf" \
    GIT_CONFIG_VALUE_0="https://github.com/RusselSand/agent-workers" \
    uv sync --frozen --no-install-project

EXPOSE 8420
CMD ["uvicorn", "spec_council.app:app", "--host", "0.0.0.0", "--port", "8420", "--reload"]
