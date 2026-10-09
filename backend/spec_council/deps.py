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
from .config import AppConfig, config_of, fitted
from .figma import Fetcher, Figma
from .store import FileStore, Store


@cache
def get_store() -> Store:
    """Советы — файлами в каталоге данных: переживают перезапуск. Один на процесс. Советы,
    сохранённые с другими моделями, читаются уже под нынешние (config.fitted)."""
    config = get_config()
    return FileStore(data_folder(), fit=lambda council: fitted(council, config))


def data_folder() -> Path:
    """COUNCIL_DATA из окружения или .env; без него — .data в корне репозитория (рядом с
    .env или, без него, над каталогом backend). Не в текущем каталоге: бэкенд запускают из
    backend с --reload, и каждая запись совета перезапускала бы сервер. Относительный путь
    из .env считается от его каталога, как у каталогов учётных записей моделей.

    Свой каталог — только вне репозитория: внутри от git и сборки докера прикрыт лишь .data,
    а другой каталог попал бы в коммит или в контекст сборки вместе с советами."""
    settings = Settings.load()
    root = settings.path.parent if settings.path else Path(__file__).resolve().parents[2]
    folder = settings.path_of("COUNCIL_DATA") or (root / ".data").resolve()
    repo = repository()
    if repo is not None and folder.is_relative_to(repo) and folder != repo / ".data":
        raise RuntimeError(
            f"Каталог советов {folder} внутри репозитория: оттуда советы попали бы в git и в "
            "сборку докера. Укажите в COUNCIL_DATA каталог вне репозитория или уберите его — "
            "тогда советы лягут в .data")
    return folder


def repository() -> Path | None:
    """Корень репозитория, из которого запущен бэкенд. None — запущен не из него: в докере
    код смонтирован без .git, и каталог советов там свой, /data/councils."""
    here = Path(__file__).resolve()
    return next((folder for folder in here.parents if (folder / ".git").exists()), None)


@cache
def get_config() -> AppConfig:
    """Совет из окружения или .env: COUNCIL_PARTICIPANT_1, COUNCIL_PARTICIPANT_2 и COUNCIL_JUDGE
    (config.config_of). Читаются один раз: поменяли — перезапустите сервер."""
    settings = Settings.load()
    return config_of(settings.get("COUNCIL_PARTICIPANT_1"), settings.get("COUNCIL_PARTICIPANT_2"),
                     settings.get("COUNCIL_JUDGE"))


def get_repositories() -> Path | None:
    """Каталог репозиториев для скана: COUNCIL_REPOS из окружения или .env (относительный —
    от каталога .env). В докере это смонтированный только на чтение /repos. Без него путь к
    рабочей копии — абсолютный."""
    return Settings.load().path_of("COUNCIL_REPOS")


def get_figma() -> Fetcher | None:
    """Figma для скана макета: персональный токен FIGMA_TOKEN из окружения или .env, с правом
    file_content:read. Без него макет не сканировать."""
    token = Settings.load().get("FIGMA_TOKEN").strip()
    return Figma(token) if token else None


@cache
def get_agents() -> AgentRunner:
    """Подключения к моделям. Одно на процесс: .env читается один раз, воркеры переиспользуются."""
    return AgentRunner(get_config().agents)


StoreDep = Annotated[Store, Depends(get_store)]
ConfigDep = Annotated[AppConfig, Depends(get_config)]
AgentsDep = Annotated[AgentRunner, Depends(get_agents)]
RepositoriesDep = Annotated[Path | None, Depends(get_repositories)]
FigmaDep = Annotated[Fetcher | None, Depends(get_figma)]

Launcher = Callable[[Callable[[], object]], None]


def get_launcher() -> Launcher:
    """Где идёт нарезка: пул приложения. Тесты подменяют на запуск тут же."""
    return launch


LauncherDep = Annotated[Launcher, Depends(get_launcher)]
