from threading import Lock

from fastapi import APIRouter, HTTPException

from ..config import MIN_PARTICIPANTS, AppConfig
from ..deps import AgentsDep, ConfigDep, LauncherDep, StoreDep
from ..models import Council, CouncilCreated, CouncilPatch, CouncilStatus, Label, Slicing
from ..pipeline import Pipeline

router = APIRouter(prefix="/councils", tags=["councils"])

NOT_FOUND = {404: {"description": "Совет не найден"}}
INVALID_MODELS = {422: {"description": "Участники или судья не из подключённых моделей"}}
NOT_RELABELABLE = {409: {"description": "Типы меняются только у готовой нарезки"}}
CANNOT_SLICE = {
    409: {"description": "Нарезка уже идёт"},
    422: {"description": "Текст пуст или к моделям совета нет подключения"},
}

# Проверка «уже идёт» и запуск — одним куском, иначе два клика запустили бы две нарезки.
_starting = Lock()


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
        raise HTTPException(404, "Совет не найден")
    return council


@router.patch("/{council_id}", responses={**NOT_FOUND, **INVALID_MODELS, **NOT_RELABELABLE})
def update_council(
    council_id: str, patch: CouncilPatch, store: StoreDep, config: ConfigDep
) -> Council:
    check_models(patch, config)
    changes = patch.model_dump(exclude_none=True, exclude={"labels"})
    with _starting:  # типы и запуск нарезки не должны разойтись
        if patch.labels is not None:
            current = store.get_council(council_id)
            if current is None:
                raise HTTPException(404, "Совет не найден")
            changes["slicing"] = relabeled(current.slicing, patch.labels)
        council = store.update_council(council_id, changes)
    if council is None:
        raise HTTPException(404, "Совет не найден")
    return council


def relabeled(slicing: Slicing | None, labels: dict[int, Label]) -> Slicing:
    """Типы, выбранные человеком. Тип совета остаётся в council_label: выбор всегда можно
    вернуть, и видно, где человек не согласился."""
    if slicing is None or slicing.state != "done":
        raise HTTPException(409, "Типы меняются только у готовой нарезки")
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
    with _starting:
        council = store.get_council(council_id)
        if council is None:
            raise HTTPException(404, "Совет не найден")
        if council.slicing and council.slicing.state == "running":
            raise HTTPException(409, "Нарезка уже идёт")
        if not council.brief.strip():
            raise HTTPException(422, "Нарезать нечего: текст пуст")
        names = {model.alias: model.display_name for model in config.models}
        # Проверяем вход заново, а не из памяти: запуск платный.
        available = agents.availability([*council.participants, council.judge], fresh=True)
        offline = [names.get(m, m) for m, ok in available.items() if not ok]
        if offline:
            raise HTTPException(422, f"Нет подключения к моделям: {', '.join(offline)}")

        def report(slicing: Slicing) -> None:
            store.update_council(council_id, {"slicing": slicing}, touch=slicing.state != "running")

        pipeline = Pipeline(council.id, council.brief, council.participants, council.judge,
                            agents, report)
        council = store.update_council(council_id, {"slicing": pipeline.state.model_copy(deep=True),
                                                    "status": CouncilStatus.slices})
    launch(pipeline.run)
    return council


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
