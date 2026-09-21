# Spec Council

Локальный инструмент подготовки ТЗ: от брифа до согласованной спецификации.
Сейчас это каркас — интерфейс и API на заглушках.

- Backend: FastAPI (Python 3.14+, uv) — `backend/spec_council`: ручки в `api/`,
  контракт в `models.py`, данные за `deps.py` (сейчас — `InMemoryStore`).
  Если Python 3.14 не установлен, `uv sync` скачает его сам (версия задана в `backend/.python-version`).
- Frontend: Vite + React + TypeScript — `frontend/src`

## Разработка в докере
Ничего ставить не нужно, кроме самого докера. Оба сервиса с hot reload.
```bash
docker compose up --build          # http://localhost:5420, API на :8420
```
После правок `package.json` или `pyproject.toml` пересоберите образы и обновите
анонимные тома (в них лежит `node_modules`):
```bash
docker compose up --build -V
```
Тесты и линтер — в тех же контейнерах:
```bash
docker compose run --rm backend pytest
docker compose run --rm backend ruff check .
docker compose run --rm frontend npm test
```

## Разработка без докера
```bash
cd backend && uv sync && uv run uvicorn spec_council.app:app --reload --port 8420
cd frontend && npm i && npm run dev    # http://localhost:5420, /api проксируется на :8420
```

## Один процесс
Фронт собирается в `backend/spec_council/static`, и FastAPI отдаёт его сам.
```bash
docker compose --profile prod up app --build    # http://localhost:8080
```
Или локально:
```bash
cd frontend && npm run build
cd ../backend && uv run uvicorn spec_council.app:app --port 8420
```

## Тесты
```bash
cd backend && uv run pytest && uv run ruff check .
cd frontend && npm test
```
