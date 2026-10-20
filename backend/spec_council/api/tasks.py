"""Этап «Задачи» — на весь совет, после потоков. Когда во всех потоках итоги утверждены и
выгружены в заметки, совет строит один план задач для coding agents по итогам всех потоков разом
(tasks.py, pipeline.TaskRun). Потом план выгружают в папку задач проекта — черновик, перевод,
запись (tasks_export.py).

План держится за то, к чему его строили (`tasks.basis`): поток с тех пор поменяли — на экране
видно, что план устарел, а сбрасывает его человек (`POST …/tasks/reset`). Сам этап ничего не
сбрасывает.
"""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ..deps import (
    AgentsDep,
    ConfigDep,
    IssuesOfDep,
    LauncherDep,
    NotesOfDep,
    RepositoriesDep,
    Store,
    StoreDep,
)
from ..export import (
    Shelf,
    design_map,
    graph_problems,
    knows_words,
    previous_of,
    repository_map,
    settled,
    untranslated,
    words_for,
)
from ..export import written as written_files
from ..issue_files import loaded
from ..models import (
    Council,
    ExportedNote,
    GroupsEdit,
    IssueNumber,
    NotePlan,
    Research,
    ScannedRepository,
    TaskPlan,
    TasksDraft,
    TasksExport,
    VanishedNote,
)
from ..notes import Catalog, NotesError
from ..pipeline import CouncilRun, NotesRun, TaskRun, start_tasks, translating
from ..prompts import language, notes_language
from ..repository import (
    Inventory,
    RepositoryError,
    Source,
    council_folders,
    same_copy,
    skipping,
    working_copy,
)
from ..tasks import (
    basis_of,
    inputs_of,
    not_ready,
    outcome_names,
    research_cited,
    research_maps,
    research_texts,
)
from ..tasks_export import aligned, drafted_tasks
from .councils import MISSING, NOT_FOUND, RunState, Slot, council_lock, reporter, running
from .documents import NO_NOTES, WriteNotes
from .groups import NOT_THESE_GROUPS, current
from .streams import CHANGING, launched_all, probed, unconnected

router = APIRouter(prefix="/councils", tags=["tasks"])

NO_ISSUES = ("У проекта нет папки задач: задайте её проекту на странице «Проекты» — задачи "
             "выгружаются файлами туда")


def council_slot(field: str) -> Slot:
    def get(council: Council) -> RunState | None:
        return getattr(council, field)

    def put(council: Council, state: RunState) -> dict:
        return {field: state}

    return Slot(get, put)


PLANNING = council_slot("tasks")
DRAFTING = council_slot("tasks_draft")


def research_of(council: Council) -> Research:
    return council.research or Research()


def code_of(research: Research, repositories: Path | None,
            folders: Sequence[tuple[Path, str]] = ()) -> list[Source]:
    """Код для плана: рабочие копии утверждённого скана исследования — заново, какие они сейчас,
    под теми же папками снимка, что и в карте, и тоже без папок совета (folders —
    council_folders). Шаг пройден без скана — кода нет. Какую-то не прочитать — 422: план без
    кода, которого ждали, молча разошёлся бы с картой."""
    step, scan = research.repository, research.scan
    if step is None or step.by != "scan" or scan is None or scan.run != step.scan_run:
        return []
    if not scan.repositories or not all(source.root for source in scan.repositories):
        raise HTTPException(422, "Скан сделан, когда совет ещё не запоминал, какую рабочую копию "
                                 "читал, — просканируйте репозиторий заново")
    return [Source(source.name, source.path, skipping(again(source, repositories), folders))
            for source in scan.repositories]


def again(source: ScannedRepository, repositories: Path | None) -> Inventory:
    """Рабочая копия скана, какая она сейчас. Тот же путь от другого каталога репозиториев —
    уже другая рабочая копия: читать её под картой прежней нельзя. Но тот же каталог, видный
    по-другому (снаружи докера и в нём), — та же копия (same_copy)."""
    try:
        found = working_copy(source.within if source.within and repositories is not None
                             else source.path, repositories)
    except RepositoryError as exc:
        raise HTTPException(422, f"Рабочую копию {source.path} не прочитать: {exc}") from None
    if not same_copy(source, found.root):
        raise HTTPException(422, f"По пути {source.path} теперь другая рабочая копия: "
                                 f"сканировали {source.root}, а сейчас это {found.root} — "
                                 "просканируйте заново")
    return found


def plannable(council: Council, notes: Path | None) -> None:
    """План строить можно: каждый поток утвердил итоги и выгружен к ним в нынешний каталог,
    план ещё не строили (или он упал), и сейчас его не строят."""
    problems = not_ready(council, str(notes) if notes is not None else None)
    if problems:
        raise HTTPException(409, "План строить рано: " + "; ".join(problems))
    if running(council.tasks):
        raise HTTPException(409, "План уже строится")
    if council.tasks is not None and council.tasks.state == "done":
        raise HTTPException(409, "План уже есть — сбросьте его, чтобы спланировать заново")


@router.post("/{council_id}/tasks", status_code=202,
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **CHANGING,
                        409: {"description": "Потоки не готовы, план уже есть или строится, или "
                                             "группы уже другие"},
                        422: {"description": "Рабочую копию утверждённого скана не прочитать"}})
def plan_tasks(council_id: str, edit: GroupsEdit, store: StoreDep, config: ConfigDep,
               agents: AgentsDep, launch: LauncherDep, notes_of: NotesOfDep,
               issues_of: IssuesOfDep, repositories: RepositoriesDep) -> Council:
    """Совет строит план задач на весь совет по утверждённым и выгруженным итогам всех потоков.
    Если исследование пройдено сканом, модели читают снимок тех же рабочих копий заново — их
    читают сейчас, и если какую-то не прочитать — 422. Нет подключения к моделям — план записан
    упавшим: его можно запустить снова."""
    # Исследование, чьи рабочие копии прочитаны: пока их читали или проверяли модели, его могли
    # сбросить или пройти заново в другой вкладке — тогда код и карта разошлись бы.
    read: list[Research] = []

    def plan() -> tuple[Council, bool]:
        council = current(council_id, store, edit)
        plannable(council, notes_of(council))
        if read and research_of(council) != read[0]:
            raise HTTPException(409, "Исследование поменялось, пока совет читал рабочие копии, — "
                                     "спланируйте снова")
        return council, True

    # Сначала дешёвое: запрос, которому всё равно откажут, рабочую копию не читает.
    with council_lock:
        council, _ = plan()
    read.append(research_of(council))
    sources = code_of(read[0], repositories,
                      council_folders(notes_of(council), issues_of(council)))

    def apply(council: Council, missing: list[str]) -> tuple[Council, list[CouncilRun]]:
        inputs = replace(inputs_of(council), cited=research_snapshot(council, notes_of(council)))
        runs: list[CouncilRun] = []
        if missing:
            state = unconnected(start_tasks(council.participants, council.judge, inputs.basis,
                                            inputs.cited), missing)
        else:
            research = research_of(council)
            runs = [TaskRun(council.id, council.participants, council.judge, agents,
                            reporter(store, council.id, PLANNING), inputs, sources=sources,
                            repository=repository_map(research), design=design_map(research))]
            state = runs[0].state.model_copy(deep=True)
        return store.update_council(council_id, {"tasks": state, "tasks_draft": None}), runs

    return launched_all(store, council_id, launch, *probed(config, agents, plan, apply))


@router.post("/{council_id}/tasks/reset",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, 423: {"description": "План строится "
                                                                              "или переводится"}})
def reset_tasks(council_id: str, edit: GroupsEdit, store: StoreDep) -> Council:
    """Человек сбрасывает план — например, когда потоки поменяли после него: план и черновик его
    выгрузки снимаются. Выгрузка остаётся: по ней новая найдёт свои файлы и номера."""
    with council_lock:
        council = current(council_id, store, edit)
        if running(council.tasks) or running(council.tasks_draft):
            raise HTTPException(423, "Совет ещё работает с планом — дождитесь его")
        council = store.update_council(council_id, {"tasks": None, "tasks_draft": None})
    if council is None:
        raise HTTPException(404, MISSING)
    return council


def issues_root(issues: Path | None) -> Path:
    if issues is None:
        raise HTTPException(422, NO_ISSUES)
    return issues


def notes_root(notes: Path | None) -> Path:
    if notes is None:
        raise HTTPException(422, NO_NOTES)
    return notes


def research_snapshot(council: Council, notes: Path | None) -> list[str]:
    """Номера каталога, что называют находки исследования, — пока заметки в каталоге: план
    запомнит их (TaskPlan.cited). Каталог не прочитать — 422: пустое запомнить нельзя, план
    строят снова, когда каталог починят."""
    if notes is None:
        return []
    try:
        catalog = Catalog.load(notes)
    except NotesError as exc:
        raise HTTPException(422, f"Каталог заметок {notes}: {exc} — почините его и спланируйте "
                                 "снова") from None
    # И что запомнила прошлая попытка плана (упавшая): заметку с тех пор могли удалить.
    return research_cited([*research_texts(council).values(), *research_maps(council)],
                          catalog.notes, council.tasks.cited if council.tasks else ())


def shelf_of(notes: Path, issues: Path) -> Shelf:
    """Каталог заметок и файлы задач, что уже лежат в папке задач. Не прочитать — 422."""
    try:
        catalog = Catalog.load(notes)
    except NotesError as exc:
        raise HTTPException(422, f"Каталог заметок {notes}: {exc}") from None
    try:
        return Shelf(catalog, notes, issues, loaded(issues))
    except NotesError as exc:
        raise HTTPException(422, f"Папка задач {issues}: {exc}") from None


def export_in(record: TasksExport | None, issues: Path) -> TasksExport | None:
    """Выгрузка плана — если она в эту папку задач: в другой её файлов нет."""
    if record is None or record.root != str(issues):
        return None
    return record


def reserved_by_others(store: Store, council_id: str, issues: Path) -> set[str]:
    """Номера задач из выгрузок других советов в эту папку: файл там могли удалить руками, но
    номер всё ещё того совета."""
    return {item.id for council in store.list_councils() if council.id != council_id
            and council.tasks_export is not None and council.tasks_export.root == str(issues)
            for item in (*council.tasks_export.notes, *council.tasks_export.numbers)}


def planned_tasks(council: Council) -> TaskPlan:
    plan = council.tasks
    if plan is None or plan.state != "done":
        raise HTTPException(409, "Сначала постройте план задач")
    return plan


def current_plan(council: Council, notes: Path) -> TaskPlan:
    """План, который можно выгружать: построен и всё ещё к тому, к чему его строили, — каждый
    поток выгружен в нынешний каталог заметок, и к тем же итогам и выгрузке. Иначе номера заметок
    в плане (OUT-…, ADR-…) — из другого каталога или прежней выгрузки, и файлы задач ссылались
    бы мимо: 409, сбросить план и спланировать заново."""
    plan = planned_tasks(council)
    problems = not_ready(council, str(notes))
    if problems or basis_of(council) != plan.basis:
        why = "; ".join(problems) or "потоки поменяли после плана"
        raise HTTPException(409, f"План устарел: {why} — сбросьте его и спланируйте заново")
    return plan


def drafted_for(council: Council, shelf: Shelf, store: Store
                ) -> tuple[list[NotePlan], list[VanishedNote], list[IssueNumber]]:
    """Что выгрузил бы совет сейчас. Не выгрузить (заметку, на которую стоит план, удалили) —
    422 с причиной."""
    fragments = {f.id: f for f in council.slicing.fragments} if council.slicing else {}
    plan = current_plan(council, shelf.root)
    try:
        return drafted_tasks(plan, fragments, shelf, export_in(council.tasks_export, shelf.issues),
                             words_for(language()), notes_language(),
                             reserved_by_others(store, council.id, shelf.issues),
                             outcome_names(council, fragments, plan.cited))
    except NotesError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/{council_id}/tasks/draft", status_code=202,
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **CHANGING,
                        409: {"description": "Плана нет, черновик уже собирается или группы уже "
                                             "другие"},
                        422: {"description": "Папки документации или задач нет, или их не "
                                             "прочитать"}})
def draft_tasks(council_id: str, edit: GroupsEdit, store: StoreDep, config: ConfigDep,
                agents: AgentsDep, launch: LauncherDep, notes_of: NotesOfDep,
                issues_of: IssuesOfDep) -> Council:
    """Черновик выгрузки плана в папку задач проекта: файл на задачу, номера на весь проект и что
    будет с каждым файлом. Язык заметок тот же, что у работы, — черновик готов сразу; другой —
    файлы переводит судья, каждый своим ходом."""
    translate = notes_language() != language() or not knows_words(language())

    def plan() -> tuple[Council, bool]:
        council = current(council_id, store, edit)
        current_plan(council, notes_root(notes_of(council)))
        issues_root(issues_of(council))
        if running(council.tasks_draft):
            raise HTTPException(409, "Черновик уже собирается")
        return council, translate

    def apply(council: Council, missing: list[str]) -> tuple[Council, list[CouncilRun]]:
        issues = issues_root(issues_of(council))
        shelf = shelf_of(notes_root(notes_of(council)), issues)
        notes, vanished, numbers = drafted_for(council, shelf, store)
        draft = TasksDraft(state="running", run=uuid4().hex[:8], plan=planned_tasks(council).run,
                           language=notes_language(), root=str(issues),
                           steps=translating(council.judge), notes=notes, vanished=vanished,
                           numbers=numbers)
        runs: list[CouncilRun] = []
        if not translate or not untranslated(draft.notes):
            # Переводить нечего, но название задачи могли перевести по-разному раньше или
            # поправить руками — строки других файлов берут его из её файла.
            previous = export_in(council.tasks_export, issues)
            draft = draft.model_copy(update={"state": "done", "steps": [],
                                             "notes": realigned(notes, previous, shelf)})
        elif missing:
            draft = unconnected(draft, missing)
        else:
            runs = [NotesRun(council.id, draft, export_in(council.tasks_export, issues), shelf,
                             council.judge, agents, reporter(store, council.id, DRAFTING))]
            draft = runs[0].state.model_copy(deep=True)
        return store.update_council(council_id, {"tasks_draft": draft}), runs

    return launched_all(store, council_id, launch, *probed(config, agents, plan, apply))


@router.post("/{council_id}/tasks/write",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS,
                        409: {"description": "Черновик уже другой или устарел, или папка задач "
                                             "поменялась, пока его смотрели"},
                        422: {"description": "Папки нет или файлы не записать"}})
def write_tasks(council_id: str, edit: WriteNotes, store: StoreDep, notes_of: NotesOfDep,
                issues_of: IssuesOfDep) -> Council:
    """Записывает черновик, который человек смотрел: с его правками текста и удалением
    отмеченных исчезнувших файлов. Файл, правленный руками после прошлой выгрузки, не
    трогается. Папка поменялась, пока смотрели черновик, — 409: номера могли занять."""
    with council_lock:
        council = current(council_id, store, edit)
        issues = issues_root(issues_of(council))
        shelf = shelf_of(notes_root(notes_of(council)), issues)
        draft = checked_draft(council, edit, issues)
        fresh, vanished, numbers = drafted_for(council, shelf, store)
        if (shape(fresh) != shape(draft.notes) or vanished != draft.vanished
                or [(n.key, n.id) for n in numbers] != [(n.key, n.id) for n in draft.numbers]):
            raise HTTPException(409, "Папка задач поменялась, пока смотрели черновик, — "
                                     "соберите его заново")
        previous = export_in(council.tasks_export, issues)
        before = {note.key: note for note in previous.notes} if previous else {}
        planned = [settled(note, previous_of(note, before), shelf) for note in draft.notes]
        if [(n.action, n.current) for n in planned] != [(n.action, n.current)
                                                        for n in draft.notes]:
            raise HTTPException(409, "Папка задач поменялась, пока смотрели черновик, — "
                                     "соберите его заново")
        saved: list[Council | None] = []

        def keep(exported: list[ExportedNote]) -> None:
            record = TasksExport(run=draft.run, plan=draft.plan, language=draft.language,
                                 root=str(issues), notes=exported, numbers=draft.numbers)
            saved.append(store.update_council(council_id, {"tasks_export": record}))

        # Название задачи человек поправил в её файле — так её зовут и строки других файлов.
        edits = {**edit.edits, **aligned(planned, {note.key: edit.edits.get(note.key, note.text)
                                                   for note in planned})}
        try:
            graph_problems(shelf.catalog, planned, vanished, edits, edit.delete)
            written_files(planned, vanished, edits, edit.delete, shelf, previous, keep)
        except NotesError as exc:
            raise HTTPException(422, str(exc)) from None
        council = saved[0]
    if council is None:
        raise HTTPException(404, MISSING)
    return council


def realigned(notes: list[NotePlan], previous: TasksExport | None,
              shelf: Shelf) -> list[NotePlan]:
    """Черновик, где задачу во всех файлах зовут названием из её файла (aligned), — и что
    теперь будет с поправленными файлами при записи."""
    before = {note.key: note for note in previous.notes} if previous else {}
    texts = aligned(notes)
    return [settled(note.model_copy(update={"text": texts[note.key]}),
                    previous_of(note, before), shelf) if note.key in texts else note
            for note in notes]


def checked_draft(council: Council, edit: WriteNotes, issues: Path) -> TasksDraft:
    draft = council.tasks_draft
    if draft is None or draft.run != edit.draft:
        raise HTTPException(409, "Черновик уже другой — посмотрите на нынешний")
    if draft.state != "done":
        raise HTTPException(409, "Черновик ещё не готов или не собрался — соберите заново")
    if council.tasks is None or draft.plan != council.tasks.run:
        raise HTTPException(409, "План построили заново — соберите черновик заново")
    if draft.root != str(issues):
        raise HTTPException(409, f"Черновик собран для другой папки задач — теперь она {issues}: "
                                 "соберите его заново")
    if draft.language != notes_language():
        raise HTTPException(409, f"Язык заметок теперь {notes_language()}, а черновик — на "
                                 f"{draft.language}: соберите его заново")
    return draft


def shape(notes: Sequence[NotePlan]) -> list[tuple[str, str, list[str], str]]:
    return [(note.key, note.id, note.links, note.generated) for note in notes]
