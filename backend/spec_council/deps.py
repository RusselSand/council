"""Единственное место, где приложение выбирает реализации.

Роуты просят StoreDep/ConfigDep и не знают, что за ними: файлы, БД или мок
из теста (app.dependency_overrides[get_store] = ...).
"""

from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Annotated

from agent_workers import Settings
from fastapi import Depends

from .agents import AgentRunner, launch
from .config import DEFAULT_CONFIG, AppConfig
from .store import FileStore, Store


@cache
def get_store() -> Store:
    """Советы — файлами в каталоге данных: переживают перезапуск. Один на процесс."""
    return FileStore(data_folder())


def data_folder() -> Path:
    """COUNCIL_DATA из окружения или .env; без него — .data в корне репозитория (рядом с
    .env или, без него, над каталогом backend). Не в текущем каталоге: бэкенд запускают из
    backend с --reload, и каждая запись совета перезапускала бы сервер. Относительный путь
    из .env считается от его каталога, как у каталогов учётных записей моделей."""
    settings = Settings.load()
    root = settings.path.parent if settings.path else Path(__file__).resolve().parents[2]
    return settings.path_of("COUNCIL_DATA") or (root / ".data").resolve()


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
