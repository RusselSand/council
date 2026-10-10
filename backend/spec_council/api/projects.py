"""Проекты: завести, поправить, удалить — и рабочие копии в каталоге репозиториев, из которых
отмечают репозитории проекта."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from ..deps import ProjectsDep, RepositoriesDep, StoreDep
from ..models import ProjectDraft, ProjectEdit, ProjectView, WorkingCopies
from ..projects import ProjectError, Projects, checked, viewed, working_copies
from .councils import council_lock

router = APIRouter(tags=["projects"])

MISSING = "Проект не найден"
NOT_FOUND = {404: {"description": MISSING}}
INVALID = {422: {"description": "Нет названия или оно уже у другого проекта, рабочей копии нет, "
                                "она вне каталога репозиториев или указана дважды, папка "
                                "документации вне его"}}


@router.get("/projects")
def list_projects(projects: ProjectsDep, repositories: RepositoriesDep) -> list[ProjectView]:
    return [viewed(project, repositories) for project in projects.list_projects()]


@router.post("/projects", status_code=201, responses=INVALID)
def create_project(draft: ProjectDraft, projects: ProjectsDep,
                   repositories: RepositoriesDep) -> ProjectView:
    draft = valid(draft, repositories)
    with council_lock:
        unique(draft, projects)
        project = projects.create_project(draft)
    return viewed(project, repositories)


@router.put("/projects/{project_id}",
            responses={**NOT_FOUND, **INVALID, 409: {"description": "Проект уже поправили"}})
def update_project(project_id: str, edit: ProjectEdit, projects: ProjectsDep,
                   repositories: RepositoriesDep) -> ProjectView:
    """Правка проекта меняет то, что совет подставит дальше: уже сделанные сканы остаются, какие
    были, а выгрузка в прежнюю папку документации в новой выгрузкой не считается. Под замком
    советов: запись заметок берёт папку проекта под ним же и не уйдёт в сменённую посреди неё."""
    if projects.get_project(project_id) is None:
        raise HTTPException(404, MISSING)
    draft = valid(edit, repositories)       # git — вне замка: копий до десяти
    with council_lock:
        before = projects.get_project(project_id)
        if before is None:
            raise HTTPException(404, MISSING)
        if before.revision != edit.revision:
            raise HTTPException(409, "Проект уже поправили, например в другой вкладке, — "
                                     "откройте его заново")
        unique(draft, projects, project_id)
        project = projects.update_project(project_id, draft)
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


def valid[D: ProjectDraft](draft: D, repositories: Path | None) -> D:
    try:
        return checked(draft, repositories)
    except ProjectError as exc:
        raise HTTPException(422, str(exc)) from None


def unique(draft: ProjectDraft, projects: Projects, project_id: str = "") -> None:
    """Название — не как у другого проекта, без учёта регистра: в списке на «Вводе» проекты
    различают только по нему."""
    name = draft.name.casefold()
    if any(project.name.casefold() == name and project.id != project_id
           for project in projects.list_projects()):
        raise HTTPException(422, f"Проект «{draft.name}» уже есть — назовите этот иначе")
