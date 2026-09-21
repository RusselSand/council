"""Хранилище проектов.

Наружу торчит только протокол Store, поэтому переезд на БД — это новый класс
и одна строка в deps.py; роуты и тесты остаются как есть.
"""

from collections.abc import Iterable
from datetime import date
from typing import Protocol
from uuid import uuid4

from .models import Council, CouncilStatus


class Store(Protocol):
    def list_councils(self) -> list[Council]: ...

    def get_council(self, council_id: str) -> Council | None: ...

    def create_council(self, *, author: str, reviewer: str) -> Council: ...


class InMemoryStore:
    """Данные живут до перезапуска процесса."""

    def __init__(self, councils: Iterable[Council] = ()) -> None:
        self._councils: dict[str, Council] = {council.id: council for council in councils}

    def list_councils(self) -> list[Council]:
        return sorted(self._councils.values(), key=lambda council: council.updated_at, reverse=True)

    def get_council(self, council_id: str) -> Council | None:
        return self._councils.get(council_id)

    def create_council(self, *, author: str, reviewer: str) -> Council:
        council = Council(
            id=uuid4().hex[:8],
            name="",  # человек ещё не назвал; подпись для пустого — на стороне фронта
            status=CouncilStatus.brief,
            author=author,
            reviewer=reviewer,
            updated_at=date.today(),
        )
        self._councils[council.id] = council
        return council


# Временные данные, чтобы интерфейс было на чём смотреть. Уедут вместе с InMemoryStore.
DEMO_COUNCILS = [
    Council(id="demo-1", name="Сервис уведомлений", status=CouncilStatus.review,
            author="sol", reviewer="fable", updated_at=date(2026, 9, 17)),
    Council(id="demo-2", name="Личный кабинет партнёра", status=CouncilStatus.brief,
            author="sol", reviewer="fable", updated_at=date(2026, 9, 15)),
    Council(id="demo-3", name="Импорт каталога", status=CouncilStatus.ready,
            author="fable", reviewer="sol", updated_at=date(2026, 9, 2)),
]
