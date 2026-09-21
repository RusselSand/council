"""Единственное место, где приложение выбирает реализации.

Роуты просят StoreDep/ConfigDep и не знают, что за ними: память, БД или мок
из теста (app.dependency_overrides[get_store] = ...).
"""

from typing import Annotated

from fastapi import Depends

from .config import DEFAULT_CONFIG, AppConfig
from .store import DEMO_RUNS, InMemoryStore, Store

_store: Store = InMemoryStore(DEMO_RUNS)


def get_store() -> Store:
    return _store


def get_config() -> AppConfig:
    return DEFAULT_CONFIG


StoreDep = Annotated[Store, Depends(get_store)]
ConfigDep = Annotated[AppConfig, Depends(get_config)]
