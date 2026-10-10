"""Шаг «Документация»: выгрузка потока в заметки — в папку документации проекта совета.

Сначала черновик: какие заметки лягут, под какими номерами, с каким текстом и что с ними будет;
язык документации другой — судья переводит. Потом запись того, что человек подтвердил, с его
правками и отмеченными к удалению исчезнувшими. Черновик — к нарезанным задачам: нарезали
заново или каталог заметок поменялся, пока смотрели черновик, — 409, собрать заново.
"""

from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ..deps import AgentsDep, ConfigDep, LauncherDep, NotesDep, NotesOfDep, Store, StoreDep
from ..export import (
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


def catalog_of(root: Path) -> Catalog:
    try:
        return Catalog.load(root)
    except NotesError as exc:
        raise HTTPException(422, f"Каталог заметок {root}: {exc}") from None


def cut(stream: Stream) -> str:
    """Задачи, к которым собирают черновик: нарезаны — их ход, иначе выгружать рано."""
    if stream.issues is None or stream.issues.state != "done":
        raise HTTPException(409, "Сначала нарежьте задачи — выгружают готовый поток")
    return stream.issues.run


def drafted_for(council: Council, group: str, stream: Stream, root: Path, catalog: Catalog,
                store: Store) -> tuple[list[NotePlan], list[VanishedNote], list[IssueNumber],
                                       list[str]]:
    """Что выгрузил бы совет сейчас. Не выгрузить (пересматриваемое решение пропало из
    каталога) — 422 с причиной."""
    fragments = {f.id: f for f in fragments_of(council, group_of(council, group))}
    try:
        return drafted(stream, fragments, catalog, root, export_in(stream.notes, root),
                       words_for(language()), notes_language(),
                       reserved_by_others(store, council.id, group, root))
    except NotesError as exc:
        raise HTTPException(422, str(exc)) from None


def reserved_by_others(store: Store, council_id: str, group: str, root: Path) -> set[str]:
    """Номера заметок и задач из выгрузок других потоков — всех советов — в этот каталог:
    заметку там могли удалить руками, но номер всё ещё того потока."""
    return {item.id for council in store.list_councils() for stream in council.streams or []
            if stream.notes is not None and stream.notes.root == str(root)
            and (council.id, stream.group) != (council_id, group)
            for item in (*stream.notes.notes, *stream.notes.numbers)}


def draft_of(council: Council, group: str, stream: Stream, root: Path, catalog: Catalog,
             store: Store) -> NotesDraft:
    notes, vanished, numbers, skipped = drafted_for(council, group, stream, root, catalog,
                                                    store)
    return NotesDraft(state="running", run=uuid4().hex[:8], issues=cut(stream),
                      language=notes_language(), root=str(root), steps=translating(council.judge),
                      notes=notes,
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
                notes: NotesDep) -> Council:
    """Черновик выгрузки потока в заметки: что ляжет в каталог, под какими номерами и что
    будет с каждой заметкой. Язык документации тот же, что у работы, — черновик готов сразу;
    другой — новые тексты переводит судья, и без подключения к нему черновик записан упавшим.
    Связки заметок («потому что», «Задачи») совет знает по-русски и по-английски: на другом
    языке их доводит тот же перевод, даже если язык заметок — язык работы."""
    root = root_of(notes)
    translate = notes_language() != language() or not knows_words(language())

    def plan() -> tuple[Council, bool]:
        council = current(council_id, store, edit)
        stream = stream_in(council, group)
        cut(stream)
        if running(stream.notes_draft):
            raise HTTPException(409, "Черновик уже собирается")
        return council, translate

    def apply(council: Council, missing: list[str]) -> tuple[Council, list[CouncilRun]]:
        stream = stream_in(council, group)
        catalog = catalog_of(root)
        draft = draft_of(council, group, stream, root, catalog, store)
        runs: list[CouncilRun] = []
        if not translate or not untranslated(draft.notes):
            draft = draft.model_copy(update={"state": "done", "steps": []})
        elif missing:
            draft = unconnected(draft, missing)
        else:
            runs = [NotesRun(council.id, draft, export_in(stream.notes, root), catalog, root,
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
                notes_of: NotesOfDep) -> Council:
    """Записывает черновик, который человек смотрел: с его правками текста и удалением
    отмеченных исчезнувших заметок. Файл, правленный руками после прошлой выгрузки, не
    трогается. Каталог поменялся, пока смотрели черновик, — 409: номера могли занять. Каталог —
    по совету, прочитанному под замком: проект совета и папку проекта меняют под тем же замком,
    и запись не уйдёт в папку, которую сменили посреди запроса."""
    with council_lock:
        council = current(council_id, store, edit)
        root = root_of(notes_of(council))
        stream = stream_in(council, group)
        draft = checked_draft(stream, edit, root)
        catalog = catalog_of(root)
        fresh, vanished, numbers, _ = drafted_for(council, group, stream, root, catalog,
                                                  store)
        if (shape(fresh) != shape(draft.notes)
                or [(n.key, n.id) for n in numbers] != [(n.key, n.id) for n in draft.numbers]
                or vanished != draft.vanished):          # и текст: удаляют то, что видели
            raise HTTPException(409, "Каталог заметок поменялся, пока смотрели черновик, — "
                                     "соберите его заново")
        previous = export_in(stream.notes, root)
        before = {note.key: note for note in previous.notes} if previous else {}
        planned = [settled(note, previous_of(note, before), catalog, root)
                   for note in draft.notes]
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
                                 root=str(root), notes=exported, numbers=draft.numbers)
            saved.append(store.update_council(council_id, {"streams": replaced(
                council, stream.model_copy(update={"notes": record}))}))

        try:
            graph_problems(catalog, planned, vanished, edit.edits, edit.delete)
            written(planned, vanished, edit.edits, edit.delete, root, previous, catalog, keep)
        except NotesError as exc:
            raise HTTPException(422, str(exc)) from None
        council = saved[0]
    if council is None:
        raise HTTPException(404, MISSING)
    return council


def checked_draft(stream: Stream, edit: WriteNotes, root: Path) -> NotesDraft:
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
    # Язык заметок сменили (COUNCIL_NOTES_LANGUAGE) после сборки: тексты черновика — на прежнем.
    if draft.language != notes_language():
        raise HTTPException(409, f"Язык заметок теперь {notes_language()}, а черновик — на "
                                 f"{draft.language}: соберите его заново")
    return draft


def shape(notes: Sequence[NotePlan]) -> list[tuple[str, str, list[str], str]]:
    """Что совет выгрузил бы: номера, связи и тексты — в итогах и номера задач, их тоже
    раздают по каталогу."""
    return [(note.key, note.id, note.links, note.generated) for note in notes]
