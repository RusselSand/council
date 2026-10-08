# Бек для разработки: зависимости живут в образе, код приезжает bind-mount'ом.
# Node — только ради CLI моделей; bookworm с обеих сторон, чтобы бинарники node подошли.
FROM node:24-bookworm-slim AS node

FROM python:3.14-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules

# git нужен uv, чтобы забрать зависимость agent-workers из GitHub, и скану репозитория: его
# inventory — список файлов рабочей копии от git. Claude Code и Codex — CLI,
# через которые agent-workers зовёт модели совета. Версии закреплены, как в kromka-agent-worker:
# разбор ответов завязан на их вывод, и тихое обновление внутри образа было бы тихой поломкой.
ARG CLAUDE_CODE_VERSION=2.1.282
ARG CODEX_VERSION=0.155.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install -g --allow-scripts=@anthropic-ai/claude-code \
        @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} @openai/codex@${CODEX_VERSION} \
    && npm cache clean --force

# Венв вне /app: иначе его затрёт bind-mount с кодом хоста (там .venv под Windows).
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    DISABLE_AUTOUPDATER=1

WORKDIR /app

# Отдельный слой: правки кода не пересобирают зависимости.
# --no-install-project — сам пакет придёт из монтирования, PYTHONPATH его найдёт.
COPY pyproject.toml uv.lock ./
# agent-workers — приватный репо. Токен только на чтение приходит build secret'ом
# agent_workers_token (см. docker-compose.yml), а не ARG: ARG остаётся в истории образа.
# Подмена адреса живёт только в окружении этой команды, в образ токен не попадает.
# Без токена compose молча передаёт пустой секрет, и git ответил бы невнятной ошибкой входа.
RUN --mount=type=secret,id=agent_workers_token \
    test -s /run/secrets/agent_workers_token \
    || { echo "Нет токена agent-workers: впишите AGENT_WORKERS_TOKEN в .env" \
              "рядом с docker-compose.yml (образец — .env.example)" >&2; exit 1; } \
    && GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0="url.https://x-access-token:$(cat /run/secrets/agent_workers_token)@github.com/RusselSand/agent-workers.insteadOf" \
    GIT_CONFIG_VALUE_0="https://github.com/RusselSand/agent-workers" \
    uv sync --frozen --no-install-project

EXPOSE 8420
CMD ["uvicorn", "spec_council.app:app", "--host", "0.0.0.0", "--port", "8420", "--reload"]
