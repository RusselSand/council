"""Spec Council API. Пока всё — заглушки с тестовыми данными."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Spec Council")

MODELS = [
    {"alias": "sol", "display_name": "GPT-5.6 Sol"},
    {"alias": "fable", "display_name": "Claude Fable 5.1"},
]

RUNS = [
    {"id": "demo-1", "name": "Сервис уведомлений", "status": "review",
     "author": "sol", "reviewer": "fable", "updated_at": "2026-09-17"},
    {"id": "demo-2", "name": "Личный кабинет партнёра", "status": "brief",
     "author": "sol", "reviewer": "fable", "updated_at": "2026-09-15"},
    {"id": "demo-3", "name": "Импорт каталога", "status": "ready",
     "author": "fable", "reviewer": "sol", "updated_at": "2026-09-02"},
]


@app.get("/api/runs")
def list_runs():
    return RUNS


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = next((r for r in RUNS if r["id"] == run_id), None)
    if run is None:
        raise HTTPException(404, "Проект не найден")
    return run


@app.post("/api/runs")
def create_run():
    return {"id": "demo-2"}


@app.get("/api/settings")
def get_settings():
    return {"models": MODELS, "default_author": "sol", "default_reviewer": "fable"}


# Собранный фронт (npm run build). Любой не-API путь отдаёт index.html,
# чтобы работали прямые ссылки на страницы SPA.
STATIC = Path(__file__).parent / "static"
if (STATIC / "index.html").exists():
    if (STATIC / "assets").is_dir():  # нет после прерванной сборки — не падаем на старте
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        return FileResponse(STATIC / "index.html")
