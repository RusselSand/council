"""Spec Council: сборка приложения. Роуты — в api/, данные — за deps.py."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import api
from .agents import shutdown
from .deps import get_store
from .spa import mount_spa


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Советы с диска — сразу при старте: каталог проверен и прерванные ходы отмечены до
    # запросов. Подменённое хранилище старт не трогает — ни его, ни настоящий каталог: его
    # получает на запрос сам FastAPI, со всем жизненным циклом зависимости (async, yield),
    # которого здесь не повторить.
    if get_store not in app.dependency_overrides:
        get_store()
    yield
    shutdown()  # идущие ходы моделей сворачиваются, оплаченное остаётся в лотке


def create_app() -> FastAPI:
    app = FastAPI(title="Spec Council", lifespan=lifespan)
    app.include_router(api.router)
    mount_spa(app, api_prefix=api.API_PREFIX)  # после роутов, иначе перехватит их
    return app


app = create_app()
