"""Шаг «Документация»: выгрузка потока в заметки — в папку документации проекта совета, а
если у проекта есть папка задач, — ещё и файл на каждую задачу, которую ничто не держит.

Сначала черновик: какие заметки и файлы задач лягут, под какими номерами, с каким текстом и что с
ними будет; язык документации другой — судья переводит. Потом запись того, что человек
подтвердил, с его правками и отмеченными к удалению исчезнувшими. Черновик — к нарезанным
задачам: нарезали заново или каталог заметок (папка задач) поменялся, пока смотрели черновик, —
409, собрать заново.
"""

from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ..deps import AgentsDep, ConfigDep, IssuesOfDep, LauncherDep, NotesOfDep, Store, StoreDep
from ..export import (
    Shelf,
    drafted,
    export_in,
    graph_problems,
    knows_words,
    previous_of,
    settled,
    untranslated,
    words_for,
    written,
)
from ..issue_files import loaded
from ..models import (
    Council,
    ExportedNote,
    GroupsEdit,
    IssueNumber,
    NotePlan,
    NotesDraft,
    NotesExport,
    Stream,
    VanishedNote,
)
from ..notes import Catalog, NotesError
from ..pipeline import CouncilRun, NotesRun, translating
from ..prompts import language, notes_language
from .councils import MISSING, NOT_FOUND, council_lock, reporter, running
from .groups import NOT_THESE_GROUPS, current
from .streams import (
    CHANGING,
    NO_STREAM,
    changed_choice,
    expired,
    fragments_of,
    group_of,
    launched_all,
    probed,
    replaced,
    stream_in,
    stream_slot,
    unconnected,
)

router = APIRouter(prefix="/councils", tags=["notes"])

NO_NOTES = ("Папки документации нет: выберите совету проект на «Вводе» или задайте проекту "
            "папку на странице «Проекты»")


class WriteNotes(GroupsEdit):
    """Человек записывает черновик draft (NotesDraft.run): edits — его правки текста по ключу
    заметки, delete — какие исчезнувшие заметки удалить."""

    draft: str
    edits: dict[str, str] = {}
    delete: list[str] = []


def root_of(notes: Path | None) -> Path:
    if notes is None:
        raise HTTPException(422, NO_NOTES)
    return notes


def shelf_of(root: Path, issues: Path | None) -> Shelf:
    """Каталог заметок и файлы задач, что уже лежат в папке задач. Не прочитать — 422."""
    try:
        catalog = Catalog.load(root)
    except NotesError as exc:
        raise HTTPException(422, f"Каталог заметок {root}: {exc}") from None
    try:
        return Shelf(catalog, root, issues, loaded(issues))
    except NotesError as exc:
        raise HTTPException(422, f"Папка задач {issues}: {exc}") from None


def cut(stream: Stream) -> str:
    """Задачи, к которым собирают черновик: нарезаны — их ход, иначе выгружать рано."""
    if stream.issues is None or stream.issues.state != "done":
        raise HTTPException(409, "Сначала нарежьте задачи — выгружают готовый поток")
    return stream.issues.run


def drafted_for(council: Council, group: str, stream: Stream, shelf: Shelf,
                store: Store) -> tuple[list[NotePlan], list[VanishedNote], list[IssueNumber],
                                       list[str]]:
    """Что выгрузил бы совет сейчас. Не выгрузить (пересматриваемое решение пропало из
    каталога) — 422 с причиной."""
    fragments = {f.id: f for f in fragments_of(council, group_of(council, group))}
    try:
        return drafted(stream, fragments, shelf,
                       export_in(stream.notes, shelf.root, shelf.issues),
                       words_for(language()), notes_language(),
                       reserved_by_others(store, council.id, group, shelf.root))
    except NotesError as exc:
        raise HTTPException(422, str(exc)) from None


def reserved_by_others(store: Store, council_id: str, group: str, root: Path) -> set[str]:
    """Номера заметок и задач из выгрузок других потоков — всех советов — в этот каталог:
    заметку там могли удалить руками, но номер всё ещё того потока."""
    return {item.id for council in store.list_councils() for stream in council.streams or []
            if stream.notes is not None and stream.notes.root == str(root)
            and (council.id, stream.group) != (council_id, group)
            for item in (*stream.notes.notes, *stream.notes.numbers)}


def draft_of(council: Council, group: str, stream: Stream, shelf: Shelf,
             store: Store) -> NotesDraft:
    notes, vanished, numbers, skipped = drafted_for(council, group, stream, shelf, store)
    return NotesDraft(state="running", run=uuid4().hex[:8], issues=cut(stream),
                      language=notes_language(), root=str(shelf.root),
                      issues_root=str(shelf.issues) if shelf.issues else "",
                      steps=translating(council.judge), notes=notes,
                      vanished=vanished, numbers=numbers, skipped=skipped)


def drafting(group: str):
    return stream_slot(group, "notes_draft")


@router.post("/{council_id}/streams/{group}/notes/draft", status_code=202,
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **NO_STREAM, **CHANGING,
                        409: {"description": "Задачи не нарезаны, черновик уже собирается или "
                                             "группы уже другие"},
                        422: {"description": "Каталог заметок не задан или его не прочитать, "
                                             "или поток в него не выгрузить"}})
def draft_notes(council_id: str, group: str, edit: GroupsEdit, store: StoreDep,
                config: ConfigDep, agents: AgentsDep, launch: LauncherDep,
                notes_of: NotesOfDep, issues_of: IssuesOfDep) -> Council:
    """Черновик выгрузки потока в заметки: что ляжет в каталог (и файлами в папку задач), под
    какими номерами и что будет с каждой заметкой. Язык документации тот же, что у работы, —
    черновик готов сразу; другой — новые тексты переводит судья, и без подключения к нему
    черновик записан упавшим. Связки заметок («потому что», «Задачи») совет знает по-русски и
    по-английски: на другом языке их доводит тот же перевод, даже если язык заметок — язык
    работы. Каталог и папка задач — по совету, прочитанному под замком, как и у записи.
    Отмеченные решения проекта с тех пор поменялись или проект сменили, а в его папке есть
    неотобранные решения, — 409, и поток снова у отбора: его решения принимали без них, и в эту
    папку им так не лечь."""
    translate = notes_language() != language() or not knows_words(language())

    def plan() -> tuple[Council, bool]:
        council = current(council_id, store, edit)
        root = root_of(notes_of(council))
        stream = stream_in(council, group)
        cut(stream)
        if running(stream.notes_draft):
            raise HTTPException(409, "Черновик уже собирается")
        expired(store, council, stream, changed_choice(root, stream))
        return council, translate

    def apply(council: Council, missing: list[str]) -> tuple[Council, list[CouncilRun]]:
        stream = stream_in(council, group)
        root = root_of(notes_of(council))
        issues = issues_of(council)
        shelf = shelf_of(root, issues)
        draft = draft_of(council, group, stream, shelf, store)
        runs: list[CouncilRun] = []
        if not translate or not untranslated(draft.notes):
            draft = draft.model_copy(update={"state": "done", "steps": []})
        elif missing:
            draft = unconnected(draft, missing)
        else:
            runs = [NotesRun(council.id, draft, export_in(stream.notes, root, issues), shelf,
                             council.judge, agents, reporter(store, council.id, drafting(group)))]
            draft = runs[0].state.model_copy(deep=True)
        return store.update_council(council_id, {"streams": replaced(
            council, stream.model_copy(update={"notes_draft": draft}))}), runs

    return launched_all(store, council_id, launch, *probed(config, agents, plan, apply))


@router.post("/{council_id}/streams/{group}/notes",
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **NO_STREAM,
                        409: {"description": "Черновик уже другой или устарел, или каталог "
                                             "заметок поменялся, пока его смотрели"},
                        422: {"description": "Каталог не задан, заметки не записать или граф "
                                             "вышел бы не по правилам"}})
def write_notes(council_id: str, group: str, edit: WriteNotes, store: StoreDep,
                notes_of: NotesOfDep, issues_of: IssuesOfDep) -> Council:
    """Записывает черновик, который человек смотрел: с его правками текста и удалением
    отмеченных исчезнувших заметок (и файлов задач). Файл, правленный руками после прошлой
    выгрузки, не трогается. Каталог поменялся, пока смотрели черновик, — 409: номера могли
    занять. Каталог и папка задач — по совету, прочитанному под замком: проект совета и папки
    проекта меняют под тем же замком, и запись не уйдёт в папку, которую сменили посреди
    запроса."""
    with council_lock:
        council = current(council_id, store, edit)
        root = root_of(notes_of(council))
        issues = issues_of(council)
        stream = stream_in(council, group)
        draft = checked_draft(stream, edit, root, issues)
        shelf = shelf_of(root, issues)
        fresh, vanished, numbers, _ = drafted_for(council, group, stream, shelf, store)
        if (shape(fresh) != shape(draft.notes)
                or [(n.key, n.id) for n in numbers] != [(n.key, n.id) for n in draft.numbers]
                or vanished != draft.vanished):          # и текст: удаляют то, что видели
            raise HTTPException(409, "Каталог заметок поменялся, пока смотрели черновик, — "
                                     "соберите его заново")
        previous = export_in(stream.notes, root, issues)
        before = {note.key: note for note in previous.notes} if previous else {}
        planned = [settled(note, previous_of(note, before), shelf) for note in draft.notes]
        # И что будет с каждой заметкой: файл, правленный руками, удалили — запись создала бы его
        # заново, хотя черновик обещал его не трогать.
        if [(n.action, n.current) for n in planned] != [(n.action, n.current)
                                                        for n in draft.notes]:
            raise HTTPException(409, "Каталог заметок поменялся, пока смотрели черновик, — "
                                     "соберите его заново")
        saved: list[Council | None] = []

        def keep(exported: list[ExportedNote]) -> None:
            # Запись о выгрузке — в той же сделке, что и файлы: не сохранилась — файлы назад.
            record = NotesExport(run=draft.run, issues=draft.issues, language=draft.language,
                                 root=str(root), issues_root=draft.issues_root, notes=exported,
                                 numbers=draft.numbers)
            saved.append(store.update_council(council_id, {"streams": replaced(
                council, stream.model_copy(update={"notes": record}))}))

        try:
            graph_problems(shelf.catalog, planned, vanished, edit.edits, edit.delete)
            written(planned, vanished, edit.edits, edit.delete, shelf, previous, keep)
        except NotesError as exc:
            raise HTTPException(422, str(exc)) from None
        council = saved[0]
    if council is None:
        raise HTTPException(404, MISSING)
    return council


def checked_draft(stream: Stream, edit: WriteNotes, root: Path,
                  issues: Path | None) -> NotesDraft:
    draft = stream.notes_draft
    if draft is None or draft.run != edit.draft:
        raise HTTPException(409, "Черновик уже другой — посмотрите на нынешний")
    if draft.state != "done":
        raise HTTPException(409, "Черновик ещё не готов или не собрался — соберите заново")
    if stream.issues is None or draft.issues != stream.issues.run:
        raise HTTPException(409, "Задачи нарезали заново — соберите черновик заново")
    # Проект совета или его папку сменили после сборки: в новую папку черновик не смотрели,
    # пусть даже номера там вышли бы те же.
    if draft.root != str(root):
        raise HTTPException(409, f"Черновик собран для другой папки документации — теперь она "
                                 f"{root}: соберите его заново")
    if draft.issues_root != (str(issues) if issues else ""):
        raise HTTPException(409, "Черновик собран для другой папки задач — проект поправили: "
                                 "соберите его заново")
    # Язык заметок сменили (COUNCIL_NOTES_LANGUAGE) после сборки: тексты черновика — на прежнем.
    if draft.language != notes_language():
        raise HTTPException(409, f"Язык заметок теперь {notes_language()}, а черновик — на "
                                 f"{draft.language}: соберите его заново")
    return draft


def shape(notes: Sequence[NotePlan]) -> list[tuple[str, str, list[str], str]]:
    """Что совет выгрузил бы: номера, связи и тексты — в итогах и номера задач, их тоже
    раздают по каталогу."""
    return [(note.key, note.id, note.links, note.generated) for note in notes]
