# Spec Council

Локальный инструмент подготовки ТЗ: от брифа до согласованной спецификации.
Сейчас это каркас — интерфейс и API на заглушках.

- Backend: FastAPI (Python 3.12, uv) — `backend/spec_council/app.py`
- Frontend: Vite + React + TypeScript — `frontend/src`

## Разработка
```bash
cd backend && uv sync && uv run uvicorn spec_council.app:app --reload --port 8000
cd frontend && npm i && npm run dev    # http://localhost:5173, /api проксируется на :8000
```

## Один процесс
```bash
cd frontend && npm run build           # собирает в backend/spec_council/static
cd ../backend && uv run uvicorn spec_council.app:app --port 8000
```

## Тесты
```bash
cd backend && uv run pytest && uv run ruff check .
```
