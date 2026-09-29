from threading import Lock

from fastapi import APIRouter, HTTPException

from ..agents import AgentRunner
from ..config import MIN_PARTICIPANTS, AppConfig
from ..deps import AgentsDep, ConfigDep, LauncherDep, StoreDep
from ..models import Council, CouncilCreated, CouncilPatch, CouncilStatus, Label, Slicing
from ..pipeline import Pipeline

router = APIRouter(prefix="/councils", tags=["councils"])

MISSING = "Совет не найден"
NOT_FOUND = {404: {"description": MISSING}}
INVALID_MODELS = {422: {"description": "Участники или судья не из подключённых моделей"}}
NOT_RELABELABLE = {409: {"description": "Типы меняются только у готовой и той же нарезки"}}
CANNOT_SLICE = {
    503: {"description": "Не запущена: сервер останавливается или состав совета меняется"},
    409: {"description": "Нарезка уже идёт или её только что запустил другой запрос"},
    422: {"description": "Текст пуст или к моделям совета нет подключения"},
}

# Проверка «уже идёт» и запуск — одним куском, иначе два клика запустили бы две нарезки.
# Тот же замок у правки типов: они меняют готовую нарезку. Внутри — только короткое: CLI
# под замком не запускаем.
_starting = Lock()

# Сколько раз проверять вход заново, если состав совета меняют прямо во время проверки.
PROBE_ATTEMPTS = 3


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
        with _starting:  # типы и запуск нарезки не должны разойтись
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


@router.post("/{council_id}/slicing", status_code=202, responses={**NOT_FOUND, **CANNOT_SLICE})
def start_slicing(council_id: str, store: StoreDep, config: ConfigDep, agents: AgentsDep,
                  launch: LauncherDep) -> Council:
    """Запускает нарезку и разметку текста советом. Идёт в фоне минутами: ход виден в
    council.slicing, фронт его опрашивает. Повтор после сбоя берёт оплаченные ответы даром."""
    def report(slicing: Slicing) -> None:
        store.update_council(council_id, {"slicing": slicing}, touch=slicing.state != "running")

    before = startable(store.get_council(council_id))
    for _ in range(PROBE_ATTEMPTS):
        # Вход — заново, а не из памяти: запуск платный. Это запуски CLI, поэтому вне замка.
        check_online(before, config, agents, fresh=True)
        with _starting:
            council = startable(store.get_council(council_id))
            # Пока шла проверка, нарезку мог запустить и даже закончить другой запрос: второй
            # запуск заплатил бы за тот же ход ещё раз и затёр бы итог.
            if run_of(council) != run_of(before):
                raise HTTPException(409, "Нарезку уже запустили")
            if lineup(council) == lineup(before):
                pipeline = Pipeline(council.id, council.brief, council.participants,
                                    council.judge, agents, report)
                council = store.update_council(council_id, {
                    "slicing": pipeline.state.model_copy(deep=True),
                    "status": CouncilStatus.slices,
                })
                break
        # Состав поменяли, пока шла проверка: проверяем новый, и снова вне замка.
        before = council
    else:
        # Не 409: 409 значит «нарезка уже есть — следите за ней», а здесь её никто не запускал.
        raise HTTPException(503, "Состав совета меняется прямо сейчас — попробуйте ещё раз")
    try:
        launch(pipeline.run)
    except RuntimeError as exc:
        # Пул закрыт: приложение останавливается. Нарезка не началась — так и записываем,
        # иначе совет навсегда остался бы «идёт» и повтор получал бы 409.
        failed = pipeline.state.model_copy(
            update={"state": "failed", "error": f"не запущена: {exc}"})
        store.update_council(council_id, {"slicing": failed})
        raise HTTPException(503, "Сервер останавливается, нарезка не запущена") from exc
    return council


def lineup(council: Council) -> frozenset[str]:
    """Кого запустит нарезка: участники и судья."""
    return frozenset([*council.participants, council.judge])


def run_of(council: Council) -> str | None:
    return council.slicing.run if council.slicing else None


def startable(council: Council | None) -> Council:
    if council is None:
        raise HTTPException(404, MISSING)
    if council.slicing and council.slicing.state == "running":
        raise HTTPException(409, "Нарезка уже идёт")
    if not council.brief.strip():
        raise HTTPException(422, "Нарезать нечего: текст пуст")
    return council


def check_online(council: Council, config: AppConfig, agents: AgentRunner, *, fresh: bool) -> None:
    names = {model.alias: model.display_name for model in config.models}
    available = agents.availability([*council.participants, council.judge], fresh=fresh)
    offline = [names.get(m, m) for m, ok in available.items() if not ok]
    if offline:
        raise HTTPException(422, f"Нет подключения к моделям: {', '.join(offline)}")


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
