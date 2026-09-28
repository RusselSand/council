"""Хранилище проектов.

Наружу торчит только протокол Store, поэтому переезд на БД — это новый класс
и одна строка в deps.py; роуты и тесты остаются как есть.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

from .models import Council, CouncilStatus


class Store(Protocol):
    def list_councils(self) -> list[Council]: ...

    def get_council(self, council_id: str) -> Council | None: ...

    def create_council(self, *, participants: list[str], judge: str) -> Council: ...

    def update_council(self, council_id: str, changes: dict[str, Any], *,
                       touch: bool = True) -> Council | None: ...


class InMemoryStore:
    """Данные живут до перезапуска процесса. Правят их и запросы, и фоновая нарезка,
    поэтому запись идёт под замком: иначе одна правка затёрла бы другую."""

    def __init__(self, councils: Iterable[Council] = ()) -> None:
        self._councils: dict[str, Council] = {council.id: council for council in councils}
        self._lock = Lock()

    def list_councils(self) -> list[Council]:
        # Свежие сверху. При равном времени выше тот, кого тронули позже: он дальше в словаре.
        councils = reversed(self._councils.values())
        return sorted(councils, key=lambda council: council.updated_at, reverse=True)

    def get_council(self, council_id: str) -> Council | None:
        return self._councils.get(council_id)

    def create_council(self, *, participants: list[str], judge: str) -> Council:
        council = Council(
            id=uuid4().hex[:8],
            name="",  # человек ещё не назвал; подпись для пустого — на стороне фронта
            status=CouncilStatus.brief,
            brief="",
            participants=list(participants),
            judge=judge,
            updated_at=datetime.now(UTC),
        )
        with self._lock:
            self._councils[council.id] = council
        return council

    def update_council(self, council_id: str, changes: dict[str, Any], *,
                       touch: bool = True) -> Council | None:
        """changes уже проверены: model_copy сам их не валидирует. touch=False — правка
        без человека (ход нарезки): совет не поднимается в списке."""
        with self._lock:
            council = self._councils.get(council_id)
            if council is None or not changes:
                return council
            if not touch:
                council = self._councils[council_id] = council.model_copy(update=changes)
                return council
            council = council.model_copy(update={**changes, "updated_at": datetime.now(UTC)})
            del self._councils[council_id]  # в конец словаря: так он выиграет и равное время
            self._councils[council_id] = council
            return council


def _demo_time(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=UTC)


# Временные данные, чтобы интерфейс было на чём смотреть. Уедут вместе с InMemoryStore.
DEMO_COUNCILS = [
    Council(id="demo-4", name="Python worker для Codex CLI", status=CouncilStatus.structure,
            brief=(
                "Хочу отдельный Python worker для Codex CLI. Сейчас сервер не может "
                "пользоваться Codex по моей подписке ChatGPT — только через API за деньги. "
                "Идея: worker крутится локально, принимает задания от сервера по HTTP, "
                "запускает codex как отдельный процесс, результат отправляет обратно на "
                "callback_url. Состояние держать в файлах, без базы. Одно задание за раз "
                "хватит. Главное — не потерять результат, если что-то упало: запуск дорогой "
                "по времени и лимитам."
            ),
            participants=["sol", "fable"], judge="fable", updated_at=_demo_time(28, 14)),
    Council(id="demo-1", name="Сервис уведомлений", status=CouncilStatus.review, brief="",
            participants=["sol", "fable"], judge="fable", updated_at=_demo_time(17)),
    Council(id="demo-2", name="Личный кабинет партнёра", status=CouncilStatus.brief, brief="",
            participants=["sol", "fable", "astra"], judge="sol", updated_at=_demo_time(15)),
    Council(id="demo-3", name="Импорт каталога", status=CouncilStatus.ready, brief="",
            participants=["sol", "fable"], judge="sol", updated_at=_demo_time(2)),
]
