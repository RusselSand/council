"""Проекты: рабочие копии и папка документации, которые совет берёт по проекту, а не вводит в
каждом потоке заново. Совет выбирает проект на «Вводе»: шаг «Репозиторий» подставляет его
рабочие копии, «Решения проекта» и «Документация» работают с его папкой.

Пути — как у скана: от каталога репозиториев (COUNCIL_REPOS) и только внутри него, без него —
абсолютные. Папка документации — там же: в докере каталог репозиториев смонтирован на запись, и
заметки ложатся рядом с кодом, в репозиторий проекта.

Проекты — файлы <id>.json в подкаталоге projects каталога советов: советы читаются из *.json
самого каталога, и проект за совет не примут.
"""

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4

from .models import Project, ProjectDraft, ProjectView, WorkingCopies
from .repository import RepositoryError, located, placed, top_of
from .store import kept, writable

log = logging.getLogger(__name__)


class ProjectError(ValueError):
    """Проект так не сохранить или его папку не найти. Текст — для человека."""


class Projects:
    """Проекты в памяти. Их правят запросы, поэтому запись — под замком."""

    def __init__(self, projects: Iterable[Project] = ()) -> None:
        self._projects = {project.id: project for project in projects}
        self._lock = Lock()

    def list_projects(self) -> list[Project]:
        """По названию: так их ищут в списке."""
        with self._lock:
            projects = list(self._projects.values())
        return sorted(projects, key=lambda project: (project.name.casefold(), project.id))

    def get_project(self, project_id: str) -> Project | None:
        with self._lock:
            return self._projects.get(project_id)

    def create_project(self, draft: ProjectDraft) -> Project:
        project = Project(id=uuid4().hex[:8], updated_at=datetime.now(UTC),
                          **draft.model_dump(include={"name", "repositories", "notes"}))
        with self._lock:
            self._keep(project)
            self._projects[project.id] = project
        return project

    def update_project(self, project_id: str, draft: ProjectDraft) -> Project | None:
        with self._lock:
            before = self._projects.get(project_id)
            if before is None:
                return None
            project = Project(id=project_id, revision=before.revision + 1,
                              updated_at=datetime.now(UTC),
                              **draft.model_dump(include={"name", "repositories", "notes"}))
            self._keep(project)
            self._projects[project_id] = project
            return project

    def delete_project(self, project_id: str) -> bool:
        with self._lock:
            if project_id not in self._projects:
                return False
            self._drop(project_id)
            del self._projects[project_id]
            return True

    def _keep(self, project: Project) -> None:
        """Сохранить проект — под замком, до того как его увидят. В памяти хранить нечего."""

    def _drop(self, project_id: str) -> None:
        """Убрать сохранённый проект."""


class FileProjects(Projects):
    """Проекты — файлы <id>.json в одном каталоге: при старте читаются все, каждая правка
    пишется на диск раньше, чем её увидят. Каталог — одного процесса, как и у советов."""

    def __init__(self, folder: Path) -> None:
        writable(folder)
        self._folder = folder
        projects = []
        for path in sorted(folder.glob("*.json")):
            try:
                projects.append(Project.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                # Файл не трогаем: его можно поправить руками, и при следующем старте он вернётся.
                log.warning("Проект из %s не прочитан, его нет в списке: %s", path, exc)
        super().__init__(projects)

    def _keep(self, project: Project) -> None:
        kept(self._folder, project.id, project.model_dump_json(indent=2))

    def _drop(self, project_id: str) -> None:
        (self._folder / f"{project_id}.json").unlink(missing_ok=True)


def checked[D: ProjectDraft](draft: D, base: Path | None) -> D:
    """Проект, каким его сохранить: название без пробелов по краям; каждая рабочая копия есть,
    её корень — внутри каталога репозиториев, и ни одна не указана дважды; папка документации —
    там же. Иначе ProjectError. Пути остаются как их ввели: пробелы по краям — часть имени."""
    name = draft.name.strip()
    if not name:
        raise ProjectError("Назовите проект")
    roots: dict[Path, str] = {}
    for path in draft.repositories:
        try:
            root = top_of(located(path, base))
        except RepositoryError as exc:
            raise ProjectError(f"{path}: {exc}") from None
        if base is not None and not root.is_relative_to(base.resolve()):
            raise ProjectError(f"{path}: корень рабочей копии {root} вне каталога "
                               f"репозиториев {base}")
        if root in roots:
            raise ProjectError(f"{roots[root]} и {path} — одна и та же рабочая копия {root}")
        roots[root] = path
    if draft.notes:
        notes_root(draft.notes, base)
    return draft.model_copy(update={"name": name})


def notes_root(text: str, base: Path | None) -> Path:
    """Папка документации по тексту человека — как путь к рабочей копии: от каталога
    репозиториев и внутри него, без него — абсолютная. Её может ещё не быть: первая выгрузка её
    создаст. Но то, что от неё уже есть, — каталог: и она сама, и ближайший существующий её
    родитель (docs/reasoning, где docs — файл, не создать)."""
    if not text.strip():
        raise ProjectError("Укажите папку документации или оставьте поле пустым")
    try:
        path = placed(text, base)
    except RepositoryError as exc:
        raise ProjectError(str(exc)) from None
    existing = next(folder for folder in (path, *path.parents) if folder.exists())
    if not existing.is_dir():
        raise ProjectError(f"Это не папка: {existing}")
    return path


def viewed(project: Project, base: Path | None) -> ProjectView:
    """Проект для экрана: с папкой документации, как её найдёт сервер, или с тем, почему её
    больше не найти."""
    view = ProjectView(**project.model_dump())
    if not project.notes:
        return view
    try:
        return view.model_copy(update={"notes_root": str(notes_root(project.notes, base))})
    except ProjectError as exc:
        return view.model_copy(update={"problem": str(exc)})


def working_copies(base: Path | None) -> WorkingCopies:
    """Рабочие копии git в каталоге репозиториев: он сам и каталоги прямо в нём — те, где есть
    .git (у подмодулей и worktree это файл), и не по ссылке наружу. Глубже не ищем: такую
    копию вписывают путём. Без каталога предлагать нечего."""
    if base is None:
        return WorkingCopies()
    root = base.resolve()
    if not root.is_dir():
        return WorkingCopies(root=str(base))
    paths = ["."] if (root / ".git").exists() else []
    try:
        children = sorted(root.iterdir(), key=lambda child: (child.name.casefold(), child.name))
    except OSError as exc:
        log.warning("Каталог репозиториев %s не прочитан: %s", root, exc)
        children = []
    for child in children:
        try:
            if (child.is_dir() and (child / ".git").exists()
                    and child.resolve().is_relative_to(root)):
                paths.append(child.name)
        except OSError:
            continue        # нет доступа — не предлагаем, путём его всё равно не взять
    return WorkingCopies(root=str(base), paths=paths)
