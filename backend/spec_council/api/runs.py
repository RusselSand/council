from fastapi import APIRouter, HTTPException

from ..deps import ConfigDep, StoreDep
from ..models import Run, RunCreated

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
def list_runs(store: StoreDep) -> list[Run]:
    return store.list_runs()


@router.post("", status_code=201)
def create_run(store: StoreDep, config: ConfigDep) -> RunCreated:
    run = store.create_run(author=config.default_author, reviewer=config.default_reviewer)
    return RunCreated(id=run.id)


@router.get("/{run_id}")
def get_run(run_id: str, store: StoreDep) -> Run:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Проект не найден")
    return run
