"""Spec Council: сборка приложения. Роуты — в api/, данные — за deps.py."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import api
from .agents import shutdown
from .deps import get_store
from .spa import mount_spa


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_store()  # советы с диска — сразу при старте: прерванные ходы отмечаются до запросов
    yield
    shutdown()  # идущие ходы моделей сворачиваются, оплаченное остаётся в лотке


def create_app() -> FastAPI:
    app = FastAPI(title="Spec Council", lifespan=lifespan)
    app.include_router(api.router)
    mount_spa(app, api_prefix=api.API_PREFIX)  # после роутов, иначе перехватит их
    return app


app = create_app()
