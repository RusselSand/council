"""Проекты: завести, поправить, удалить — и рабочие копии в каталоге репозиториев, из которых
отмечают репозитории проекта."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from ..deps import ProjectsDep, RepositoriesDep, StoreDep
from ..models import ProjectDraft, ProjectView, WorkingCopies
from ..projects import ProjectError, checked, viewed, working_copies
from .councils import council_lock

router = APIRouter(tags=["projects"])

MISSING = "Проект не найден"
NOT_FOUND = {404: {"description": MISSING}}
INVALID = {422: {"description": "Нет названия, рабочей копии нет, она вне каталога "
                                "репозиториев или указана дважды, папка документации вне его"}}


@router.get("/projects")
def list_projects(projects: ProjectsDep, repositories: RepositoriesDep) -> list[ProjectView]:
    return [viewed(project, repositories) for project in projects.list_projects()]


@router.post("/projects", status_code=201, responses=INVALID)
def create_project(draft: ProjectDraft, projects: ProjectsDep,
                   repositories: RepositoriesDep) -> ProjectView:
    return viewed(projects.create_project(valid(draft, repositories)), repositories)


@router.put("/projects/{project_id}", responses={**NOT_FOUND, **INVALID})
def update_project(project_id: str, draft: ProjectDraft, projects: ProjectsDep,
                   repositories: RepositoriesDep) -> ProjectView:
    """Правка проекта меняет то, что совет подставит дальше: уже сделанные сканы остаются, какие
    были, а выгрузка в прежнюю папку документации в новой выгрузкой не считается."""
    if projects.get_project(project_id) is None:
        raise HTTPException(404, MISSING)
    project = projects.update_project(project_id, valid(draft, repositories))
    if project is None:
        raise HTTPException(404, MISSING)
    return viewed(project, repositories)


@router.delete("/projects/{project_id}", status_code=204,
               responses={**NOT_FOUND, 409: {"description": "Проект выбран у советов"}})
def delete_project(project_id: str, projects: ProjectsDep, store: StoreDep) -> Response:
    """Удалить можно проект, который не выбран ни у одного совета: иначе их выгрузки и решения
    проекта молча остались бы без папки. Под замком советов — чтобы его не выбрали тем временем."""
    with council_lock:
        users = [f"«{council.name}»" if council.name else council.id
                 for council in store.list_councils() if council.project == project_id]
        if users:
            raise HTTPException(409, f"Проект выбран у советов: {', '.join(users)} — сначала "
                                     "выберите им другой")
        if not projects.delete_project(project_id):
            raise HTTPException(404, MISSING)
    return Response(status_code=204)


@router.get("/repositories")
def list_working_copies(repositories: RepositoriesDep) -> WorkingCopies:
    return working_copies(repositories)


def valid(draft: ProjectDraft, repositories: Path | None) -> ProjectDraft:
    try:
        return checked(draft, repositories)
    except ProjectError as exc:
        raise HTTPException(422, str(exc)) from None
