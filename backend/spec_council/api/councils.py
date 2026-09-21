from fastapi import APIRouter, HTTPException

from ..deps import ConfigDep, StoreDep
from ..models import Council, CouncilCreated

router = APIRouter(prefix="/councils", tags=["councils"])


@router.get("")
def list_councils(store: StoreDep) -> list[Council]:
    return store.list_councils()


@router.post("", status_code=201)
def create_council(store: StoreDep, config: ConfigDep) -> CouncilCreated:
    council = store.create_council(author=config.default_author, reviewer=config.default_reviewer)
    return CouncilCreated(id=council.id)


@router.get("/{council_id}")
def get_council(council_id: str, store: StoreDep) -> Council:
    council = store.get_council(council_id)
    if council is None:
        raise HTTPException(404, "Совет не найден")
    return council
