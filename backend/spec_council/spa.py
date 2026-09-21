"""Раздача собранного фронта (`npm run build`).

Нужна только в сборке «один контейнер»: в разработке фронт отдаёт vite,
сборки нет — и приложение поднимается без неё.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# В репозитории сборку кладёт vite, в образ — докер, рядом с пакетом. Свежая сборка
# из dist идёт первой: в чекаутах, где собирали по-старому, рядом с пакетом мог остаться
# static/ — он не отслеживается гитом, сам не исчезнет и иначе перекрыл бы новый фронт.
_CANDIDATES = (
    Path(__file__).resolve().parents[2] / "frontend" / "dist",
    Path(__file__).parent / "static",
)
STATIC = next((p for p in _CANDIDATES if (p / "index.html").exists()), _CANDIDATES[-1])


def mount_spa(app: FastAPI, *, api_prefix: str) -> None:
    """Любой не-API путь отдаёт index.html, чтобы работали прямые ссылки на страницы SPA.

    Вызывать последним: catch-all перехватит всё, что зарегистрировано после него.
    """
    index = STATIC / "index.html"
    if not index.exists():  # фронт не собран
        return

    if (STATIC / "assets").is_dir():  # нет после прерванной сборки — не падаем на старте
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    api_root = api_prefix.strip("/")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        # Неизвестный /api/... — это ошибка API, а не страница: фронт ждёт JSON.
        if path == api_root or path.startswith(f"{api_root}/"):
            raise HTTPException(404, "Not Found")
        return FileResponse(index)
