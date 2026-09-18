# Spec Council

Локальный инструмент подготовки ТЗ: от брифа до согласованной спецификации.
Сейчас это каркас — интерфейс и API на заглушках.

- Backend: FastAPI (Python 3.14+, uv) — `backend/spec_council/app.py`.
  Если Python 3.14 не установлен, `uv sync` скачает его сам (версия задана в `backend/.python-version`).
- Frontend: Vite + React + TypeScript — `frontend/src`

## Разработка
```bash
cd backend && uv sync && uv run uvicorn spec_council.app:app --reload --port 8420
cd frontend && npm i && npm run dev    # http://localhost:5420, /api проксируется на :8420
```

## Один процесс
```bash
cd frontend && npm run build           # собирает в backend/spec_council/static
cd ../backend && uv run uvicorn spec_council.app:app --port 8420
```

## Тесты
```bash
cd backend && uv run pytest && uv run ruff check .
cd frontend && npm test
```
