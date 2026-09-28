from fastapi import APIRouter, HTTPException

from ..config import MIN_PARTICIPANTS, AppConfig
from ..deps import ConfigDep, StoreDep
from ..models import Council, CouncilCreated, CouncilPatch

router = APIRouter(prefix="/councils", tags=["councils"])

NOT_FOUND = {404: {"description": "Совет не найден"}}
INVALID_MODELS = {422: {"description": "Участники или судья не из подключённых моделей"}}


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


@router.patch("/{council_id}", responses={**NOT_FOUND, **INVALID_MODELS})
def update_council(
    council_id: str, patch: CouncilPatch, store: StoreDep, config: ConfigDep
) -> Council:
    check_models(patch, config)
    council = store.update_council(council_id, patch.model_dump(exclude_none=True))
    if council is None:
        raise HTTPException(404, "Совет не найден")
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
