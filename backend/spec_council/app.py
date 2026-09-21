"""Spec Council: сборка приложения. Роуты — в api/, данные — за deps.py."""

from fastapi import FastAPI

from . import api
from .spa import mount_spa


def create_app() -> FastAPI:
    app = FastAPI(title="Spec Council")
    app.include_router(api.router)
    mount_spa(app, api_prefix=api.API_PREFIX)  # после роутов, иначе перехватит их
    return app


app = create_app()
