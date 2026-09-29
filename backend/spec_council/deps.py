"""Единственное место, где приложение выбирает реализации.

Роуты просят StoreDep/ConfigDep и не знают, что за ними: память, БД или мок
из теста (app.dependency_overrides[get_store] = ...).
"""

from collections.abc import Callable
from functools import cache
from typing import Annotated

from fastapi import Depends

from .agents import AgentRunner, launch
from .config import DEFAULT_CONFIG, AppConfig
from .store import DEMO_COUNCILS, InMemoryStore, Store

_store: Store = InMemoryStore(DEMO_COUNCILS)


def get_store() -> Store:
    return _store


def get_config() -> AppConfig:
    return DEFAULT_CONFIG


@cache
def get_agents() -> AgentRunner:
    """Подключения к моделям. Одно на процесс: .env читается один раз, воркеры переиспользуются."""
    return AgentRunner(DEFAULT_CONFIG.agents)


StoreDep = Annotated[Store, Depends(get_store)]
ConfigDep = Annotated[AppConfig, Depends(get_config)]
AgentsDep = Annotated[AgentRunner, Depends(get_agents)]

Launcher = Callable[[Callable[[], object]], None]


def get_launcher() -> Launcher:
    """Где идёт нарезка: пул приложения. Тесты подменяют на запуск тут же."""
    return launch


LauncherDep = Annotated[Launcher, Depends(get_launcher)]
