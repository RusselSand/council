"""Хранилище проектов.

Наружу торчит только протокол Store, поэтому переезд на БД — это новый класс
и одна строка в deps.py; роуты и тесты остаются как есть.
"""

import logging
import os
from collections import OrderedDict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

from .models import Council, CouncilStatus, IdeaDiscovery, Slicing, Structure

log = logging.getLogger(__name__)

# Почему ход, шедший при остановке сервера, записан упавшим.
INTERRUPTED = "прерван: сервер остановился, пока шёл ход"


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
        # Порядок — кого трогали позже, тот дальше: move_to_end двигает без удаления, и
        # чтение не застанет совет отсутствующим посреди записи.
        self._councils: OrderedDict[str, Council] = OrderedDict((c.id, c) for c in councils)
        self._lock = Lock()

    def list_councils(self) -> list[Council]:
        # Снимок под замком: запись переставляет совет в словаре, и обход без замка
        # мог бы пропустить его, повторить или упасть на изменившемся размере.
        with self._lock:
            councils = list(self._councils.values())
        # Свежие сверху. При равном времени выше тот, кого тронули позже: он дальше в словаре.
        return sorted(reversed(councils), key=lambda council: council.updated_at, reverse=True)

    def get_council(self, council_id: str) -> Council | None:
        with self._lock:
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
            self._keep(council)
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
                council = council.model_copy(update=changes)
                self._keep(council)
                self._councils[council_id] = council
                return council
            council = council.model_copy(update={**changes, "updated_at": datetime.now(UTC)})
            self._keep(council)
            self._councils[council_id] = council
            self._councils.move_to_end(council_id)  # так он выиграет и равное время
            return council

    def _keep(self, council: Council) -> None:
        """Сохранить совет — под замком, до того как его увидят. В памяти хранить нечего."""


class FileStore(InMemoryStore):
    """Советы — файлы <id>.json в одном каталоге: переживают перезапуск. При старте читаются
    все, дальше живут в памяти, а каждая правка пишется на диск раньше, чем её увидят: не
    записалась — правки нет. Каталог — одного процесса: второй не увидел бы чужих правок."""

    def __init__(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self._folder = folder
        councils = []
        for path in sorted(folder.glob("*.json")):
            try:
                council = Council.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                # Файл не трогаем: его можно поправить руками, и при следующем старте он вернётся.
                log.warning("Совет из %s не прочитан, его нет в списке: %s", path, exc)
                continue
            stopped = interrupted(council)
            if stopped is not council:
                self._keep(stopped)
            councils.append(stopped)
        super().__init__(sorted(councils, key=lambda council: council.updated_at))

    def _keep(self, council: Council) -> None:
        # Сначала во временный файл, потом подменой: процесс, оборванный посреди записи, совет
        # не испортит. Без fsync: в докере он стоит 60–120 мс на запись, а пишем под замком
        # на каждую правку. От пропадания питания это не спасает — для локального
        # инструмента цена того не стоит.
        path = self._folder / f"{council.id}.json"
        part = path.with_name(f"{path.name}.part")
        part.write_text(council.model_dump_json(indent=2), encoding="utf-8")
        os.replace(part, path)


def interrupted(council: Council) -> Council:
    """Совет, прочитанный после перезапуска. Ходы, которые шли, уже не идут: процесс с ними
    остановлен. Записываем их упавшими — тогда их можно запустить снова, а ответы, за которые
    уже заплачено, повтор возьмёт из лотка даром. Ничего не шло — тот же совет."""
    changes: dict[str, Any] = {}
    for field in ("slicing", "structure"):
        state = getattr(council, field)
        if running(state):
            changes[field] = halted(state)
    if council.streams and any(running(stream.discovery) for stream in council.streams):
        changes["streams"] = [
            stream.model_copy(update={"discovery": halted(stream.discovery)})
            if running(stream.discovery) else stream
            for stream in council.streams
        ]
    return council.model_copy(update=changes) if changes else council


def running(state: Slicing | Structure | IdeaDiscovery | None) -> bool:
    return state is not None and state.state == "running"


def halted[S: (Slicing, Structure, IdeaDiscovery)](state: S) -> S:
    """Ход, прерванный остановкой: упал, и шаги с моделями, что работали, — тоже."""
    steps = [step.model_copy(update={
        "state": "failed" if step.state == "running" else step.state,
        "runs": [run.model_copy(update={"state": "failed", "error": INTERRUPTED})
                 if run.state == "running" else run for run in step.runs],
    }) for step in state.steps]
    return state.model_copy(update={"state": "failed", "error": INTERRUPTED, "steps": steps})
