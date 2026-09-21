# Spec Council

Локальный инструмент подготовки ТЗ: от брифа до согласованной спецификации.
Сейчас это каркас — интерфейс и API на заглушках.

- Backend: FastAPI (Python 3.14+, uv) — `backend/spec_council`: ручки в `api/`,
  контракт в `models.py`, данные за `deps.py` (пока `InMemoryStore`).
- Frontend: Vite + React + TypeScript — `frontend/src`.
- Надписи: `frontend/src/i18n` — словари `ru.ts` и `en.ts` (i18next). Язык берётся из
  настроек браузера, переключается в шапке и запоминается в localStorage.

Команды ниже даны по одной на строку: так они одинаково работают в bash и в PowerShell.

## Разработка в докере
Ничего ставить не нужно, кроме самого докера. Оба сервиса с hot reload.
```bash
docker compose up --build
```
Фронт — http://localhost:5420, API — http://localhost:8420.

После правок `package.json` или `pyproject.toml` пересоберите образы и обновите
анонимные тома (в них лежит `node_modules`):
```bash
docker compose up --build -V
```

## Разработка без докера
Две консоли. `uv` сам поставит зависимости и при необходимости скачает Python 3.14
(версия задана в `backend/.python-version`).
```bash
cd backend
uv run uvicorn spec_council.app:app --reload --port 8420
```
```bash
cd frontend
npm i
npm run dev
```
Фронт на http://localhost:5420, запросы `/api` проксирует на бэкенд.

## Один процесс
Фронт собирается в `frontend/dist`, и дальше его отдаёт сам FastAPI — включая прямые
ссылки на страницы вроде `/councils/demo-1/brief`.
```bash
docker compose --profile prod up app --build
```
Открывается на http://localhost:8080. То же самое локально, на http://localhost:8420:
```bash
cd frontend
npm run build
cd ../backend
uv run uvicorn spec_council.app:app --port 8420
```

## Тесты и линтер
```bash
cd backend
uv run pytest
uv run ruff check .
```
```bash
cd frontend
npm test
```
Или в контейнерах, если локальных зависимостей нет:
```bash
docker compose run --rm backend pytest
docker compose run --rm backend ruff check .
docker compose run --rm frontend npm test
```
