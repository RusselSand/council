# Бек для разработки: зависимости живут в образе, код приезжает bind-mount'ом.
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

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
RUN uv sync --frozen --no-install-project

EXPOSE 8420
CMD ["uvicorn", "spec_council.app:app", "--host", "0.0.0.0", "--port", "8420", "--reload"]
