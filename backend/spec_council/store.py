"""Хранилище проектов.

Наружу торчит только протокол Store, поэтому переезд на БД — это новый класс
и одна строка в deps.py; роуты и тесты остаются как есть.
"""

from collections.abc import Iterable
from datetime import date
from typing import Protocol
from uuid import uuid4

from .models import Run, RunStatus


class Store(Protocol):
    def list_runs(self) -> list[Run]: ...

    def get_run(self, run_id: str) -> Run | None: ...

    def create_run(self, *, author: str, reviewer: str) -> Run: ...


class InMemoryStore:
    """Данные живут до перезапуска процесса."""

    def __init__(self, runs: Iterable[Run] = ()) -> None:
        self._runs: dict[str, Run] = {run.id: run for run in runs}

    def list_runs(self) -> list[Run]:
        return sorted(self._runs.values(), key=lambda run: run.updated_at, reverse=True)

    def get_run(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def create_run(self, *, author: str, reviewer: str) -> Run:
        run = Run(
            id=uuid4().hex[:8],
            name="Новый бриф",
            status=RunStatus.brief,
            author=author,
            reviewer=reviewer,
            updated_at=date.today(),
        )
        self._runs[run.id] = run
        return run


# Временные данные, чтобы интерфейс было на чём смотреть. Уедут вместе с InMemoryStore.
DEMO_RUNS = [
    Run(id="demo-1", name="Сервис уведомлений", status=RunStatus.review,
        author="sol", reviewer="fable", updated_at=date(2026, 9, 17)),
    Run(id="demo-2", name="Личный кабинет партнёра", status=RunStatus.brief,
        author="sol", reviewer="fable", updated_at=date(2026, 9, 15)),
    Run(id="demo-3", name="Импорт каталога", status=RunStatus.ready,
        author="fable", reviewer="sol", updated_at=date(2026, 9, 2)),
]
