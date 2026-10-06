from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Any

from fastapi import APIRouter, HTTPException

from ..agents import AgentRunner
from ..config import MIN_PARTICIPANTS, AppConfig
from ..deps import AgentsDep, ConfigDep, Launcher, LauncherDep, Store, StoreDep
from ..models import (
    Council,
    CouncilCreated,
    CouncilPatch,
    CouncilStatus,
    IdeaDiscovery,
    Label,
    Slicing,
    Structure,
)
from ..pipeline import CouncilRun, GroupingRun, SlicingRun

router = APIRouter(prefix="/councils", tags=["councils"])

MISSING = "Совет не найден"
NOT_FOUND = {404: {"description": MISSING}}
INVALID_MODELS = {422: {"description": "Участники или судья не из подключённых моделей"}}
NOT_RELABELABLE = {409: {"description": "Типы меняются только у готовой и той же нарезки"}}
CANNOT_START = {
    503: {"description": "Не запущено: сервер останавливается или состав совета меняется"},
    409: {"description": "Этот ход уже идёт или его только что запустил другой запрос"},
    423: {"description": "Идёт другой ход совета, от которого этот зависит"},
    422: {"description": "Нечего обрабатывать или к моделям совета нет подключения"},
}

# Проверка «уже идёт» и запуск — одним куском, иначе два клика запустили бы два хода.
# Тот же замок у правки типов и групп: они меняют готовый итог хода. Внутри — только
# короткое: CLI под замком не запускаем.
council_lock = Lock()

# Сколько раз проверять вход заново, если состав совета меняют прямо во время проверки.
PROBE_ATTEMPTS = 3

RunState = Slicing | Structure | IdeaDiscovery


@dataclass(frozen=True)
class Slot:
    """Где в совете лежит ход: поле совета (нарезка, группы) или поиск идеи потока. put —
    правка совета, которая кладёт ход на место; revision — сколько раз итог хода правил
    человек: новый ход не должен молча затереть принятую правку."""

    get: Callable[[Council], RunState | None]
    put: Callable[[Council, RunState], dict[str, Any]]
    revision: Callable[[Council], int] = lambda council: 0


SLICING = Slot(lambda council: council.slicing, lambda council, state: {"slicing": state})
STRUCTURE = Slot(lambda council: council.structure, lambda council, state: {"structure": state},
                 lambda council: council.structure.revision if council.structure else 0)


@router.get("")
def list_councils(store: StoreDep) -> list[Council]:
    return store.list_councils()


@router.post("", status_code=201)
def create_council(store: StoreDep, config: ConfigDep) -> CouncilCreated:
    council = store.create_council(
        participants=config.default_participants, judge=config.default_judge
    )
    return CouncilCreated(id=council.id)


@router.get("/{council_id}", responses=NOT_FOUND)
def get_council(council_id: str, store: StoreDep) -> Council:
    council = store.get_council(council_id)
    if council is None:
        raise HTTPException(404, MISSING)
    return council


@router.patch("/{council_id}", responses={**NOT_FOUND, **INVALID_MODELS, **NOT_RELABELABLE})
def update_council(
    council_id: str, patch: CouncilPatch, store: StoreDep, config: ConfigDep
) -> Council:
    check_models(patch, config)
    changes = patch.model_dump(exclude_none=True, exclude={"labels", "slicing_run"})
    if patch.labels is None:
        council = store.update_council(council_id, changes)
    else:
        with council_lock:  # типы и запуск нарезки не должны разойтись
            current = store.get_council(council_id)
            if current is None:
                raise HTTPException(404, MISSING)
            changes["slicing"] = relabeled(current.slicing, patch.labels, patch.slicing_run)
            council = store.update_council(council_id, changes)
    if council is None:
        raise HTTPException(404, MISSING)
    return council


def relabeled(slicing: Slicing | None, labels: dict[int, Label], run: str | None) -> Slicing:
    """Типы, выбранные человеком. Тип совета остаётся в council_label: выбор всегда можно
    вернуть, и видно, где человек не согласился."""
    if run is None:
        raise HTTPException(422, "Типы без slicing_run: непонятно, к какой нарезке они")
    if slicing is None or slicing.state != "done":
        raise HTTPException(409, "Типы меняются только у готовой нарезки")
    if slicing.run != run:
        raise HTTPException(409, "Нарезку уже переделали: эти типы относятся к прежней")
    unknown = sorted(set(labels) - {fragment.id for fragment in slicing.fragments})
    if unknown:
        raise HTTPException(422, f"Нет фрагментов: {', '.join(map(str, unknown))}")
    fragments = [fragment.model_copy(update={"label": labels.get(fragment.id, fragment.label)})
                 for fragment in slicing.fragments]
    return slicing.model_copy(update={"fragments": fragments})


@router.post("/{council_id}/slicing", status_code=202, responses={**NOT_FOUND, **CANNOT_START})
def start_slicing(council_id: str, store: StoreDep, config: ConfigDep, agents: AgentsDep,
                  launch: LauncherDep) -> Council:
    """Запускает нарезку и разметку текста советом. Идёт в фоне минутами: ход виден в
    council.slicing, фронт его опрашивает. Повтор после сбоя берёт оплаченные ответы даром.
    Прежние группы при этом сбрасываются: они были про прежние фрагменты."""
    def ready(council: Council) -> None:
        if running(council.structure):
            raise HTTPException(
                423, "Идёт раскладка по группам — дождитесь её, потом нарезайте заново")
        if seeking(council):
            raise HTTPException(
                423, "Совет ищет идеи потоков — дождитесь его, потом нарезайте заново")
        if not council.brief.strip():
            raise HTTPException(422, "Нарезать нечего: текст пуст")

    return start_run(
        council_id, store, config, agents, launch, SLICING, ready, CouncilStatus.slices,
        lambda council, report: SlicingRun(council.id, council.brief, council.participants,
                                           council.judge, agents, report),
        also={"structure": None, "streams": None},
    )


@router.post("/{council_id}/structure", status_code=202, responses={**NOT_FOUND, **CANNOT_START})
def start_structure(council_id: str, store: StoreDep, config: ConfigDep, agents: AgentsDep,
                    launch: LauncherDep) -> Council:
    """Запускает раскладку фрагментов готовой нарезки по группам, в фоне. Ход — в
    council.structure. Типы берутся текущие, с правками человека. Новая раскладка снимает
    подтверждение групп: потоки были про прежние."""
    def ready(council: Council) -> None:
        if running(council.slicing):
            raise HTTPException(423, "Нарезка ещё идёт — группы после неё")
        if seeking(council):
            raise HTTPException(
                423, "Совет ищет идеи потоков — дождитесь его, потом раскладывайте заново")
        if council.slicing is None or council.slicing.state != "done":
            raise HTTPException(422, "Раскладывать нечего: сначала нужна готовая нарезка")

    return start_run(
        council_id, store, config, agents, launch, STRUCTURE, ready, CouncilStatus.structure,
        lambda council, report: GroupingRun(council.id, council.slicing, council.participants,
                                            council.judge, agents, report),
        also={"streams": None},
    )


def start_run(council_id: str, store: Store, config: AppConfig, agents: AgentRunner,
              launch: Launcher, slot: Slot, ready: Callable[[Council], None],
              status: CouncilStatus | None, build: Callable[[Council, Callable], CouncilRun],
              also: dict | None = None) -> Council:
    """Общий запуск хода совета: нарезки, групп, поиска идеи потока. status None — статус
    совета ход не меняет.

    Вход проверяется заново, а не из памяти: запуск платный. Это запуски CLI, поэтому вне
    замка; под замком — только сверка: не запустил ли ход кто-то другой и не поменялся ли
    состав совета, пока шла проверка. Поменялся — проверяем новый, и снова вне замка.
    """
    report = reporter(store, council_id, slot)

    def startable(council: Council | None) -> Council:
        if council is None:
            raise HTTPException(404, MISSING)
        if running(slot.get(council)):
            raise HTTPException(409, "Этот ход уже идёт")
        ready(council)
        return council

    before = startable(store.get_council(council_id))
    for _ in range(PROBE_ATTEMPTS):
        check_online(before, config, agents, fresh=True)
        with council_lock:
            council = startable(store.get_council(council_id))
            # Пока шла проверка, ход мог запустить и даже закончить другой запрос: второй
            # запуск заплатил бы за те же ходы моделей ещё раз и затёр бы итог.
            if run_of(slot.get(council)) != run_of(slot.get(before)):
                raise HTTPException(409, "Этот ход уже запустили")
            # Или группы поправили в другой вкладке: новый ход молча затёр бы принятую правку.
            # Пусть человек сначала её увидит.
            if slot.revision(council) != slot.revision(before):
                raise HTTPException(409, "Группы поправили, пока шла проверка, — посмотрите на них")
            if lineup(council) == lineup(before):
                pipeline = build(council, report)
                council = store.update_council(council_id, {
                    **slot.put(council, pipeline.state.model_copy(deep=True)),
                    **({"status": status} if status else {}), **(also or {}),
                })
                break
        before = council
    else:
        # Не 409: 409 значит «ход уже есть — следите за ним», а здесь его никто не запускал.
        raise HTTPException(503, "Состав совета меняется прямо сейчас — попробуйте ещё раз")
    if not launched(launch, pipeline, report):
        raise HTTPException(503, "Сервер останавливается, ход не запущен")
    return council


def launched(launch: Launcher, pipeline: CouncilRun, report: Callable[[RunState], None]) -> bool:
    """Отдать ход в пул. Пул закрыт — приложение останавливается: ход не начался, так и
    записываем, иначе совет навсегда остался бы «идёт» и повтор получал бы 409."""
    try:
        launch(pipeline.run)
    except RuntimeError as exc:
        report(pipeline.state.model_copy(update={"state": "failed", "error": f"не запущен: {exc}"}))
        return False
    return True


def reporter(store: Store, council_id: str, slot: Slot) -> Callable[[RunState], None]:
    """Отчёт хода: кладёт его на место, если там всё ещё он. Совет читается и пишется под
    замком: ходы потоков идут разом и пишут в один список — без замка один затёр бы другой.
    Ход, которого на месте уже нет (группы разложили или поправили заново), не пишется."""
    def report(state: RunState) -> None:
        with council_lock:
            council = store.get_council(council_id)
            current = slot.get(council) if council else None
            if current is None or current.run != state.run:
                return
            store.update_council(council_id, slot.put(council, state),
                                 touch=state.state != "running")
    return report


def running(state: RunState | None) -> bool:
    return state is not None and state.state == "running"


def seeking(council: Council) -> bool:
    """Совет ищет идею хоть одного потока: новая нарезка, раскладка или другой состав групп
    стёрли бы потоки из-под него."""
    return any(running(stream.discovery) for stream in council.streams or [])


def lineup(council: Council) -> frozenset[str]:
    """Кого запустит ход: участники и судья."""
    return frozenset([*council.participants, council.judge])


def run_of(state: RunState | None) -> str | None:
    return state.run if state else None


def offline(council: Council, config: AppConfig, agents: AgentRunner, *, fresh: bool,
            ) -> list[str]:
    """Модели совета без подключения — их имена для человека."""
    names = {model.alias: model.display_name for model in config.models}
    available = agents.availability([*council.participants, council.judge], fresh=fresh)
    return [names.get(m, m) for m, ok in available.items() if not ok]


def check_online(council: Council, config: AppConfig, agents: AgentRunner, *, fresh: bool) -> None:
    missing = offline(council, config, agents, fresh=fresh)
    if missing:
        raise HTTPException(422, f"Нет подключения к моделям: {', '.join(missing)}")


def check_models(patch: CouncilPatch, config: AppConfig) -> None:
    """Участники и судья — только из подключённых моделей. Судья может и не участвовать."""
    known = {model.alias for model in config.models}
    if patch.participants is not None:
        if len(set(patch.participants)) != len(patch.participants):
            raise HTTPException(422, "Модель указана в совете дважды")
        if len(patch.participants) < MIN_PARTICIPANTS:
            raise HTTPException(422, f"Нужны минимум {MIN_PARTICIPANTS} модели")
        unknown = [alias for alias in patch.participants if alias not in known]
        if unknown:
            raise HTTPException(422, f"Неизвестные модели: {', '.join(unknown)}")
    if patch.judge is not None and patch.judge not in known:
        raise HTTPException(422, f"Неизвестная модель: {patch.judge}")
