"""Шаг «Документация»: выгрузка потока в заметки проекта (COUNCIL_NOTES).

Сначала черновик: какие заметки лягут, под какими номерами, с каким текстом и что с ними будет;
язык документации другой — судья переводит. Потом запись того, что человек подтвердил, с его
правками и отмеченными к удалению исчезнувшими. Черновик — к нарезанным задачам: нарезали
заново или каталог заметок поменялся, пока смотрели черновик, — 409, собрать заново.
"""

from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ..deps import AgentsDep, ConfigDep, LauncherDep, NotesDep, StoreDep
from ..export import (
    drafted,
    graph_problems,
    knows_words,
    settled,
    untranslated,
    words_for,
    written,
)
from ..models import Council, GroupsEdit, NotePlan, NotesDraft, NotesExport, Stream
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

NO_NOTES = "Каталог заметок не задан: впишите COUNCIL_NOTES в .env и перезапустите сервер"


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


def draft_of(council: Council, group: str, stream: Stream, root: Path,
             catalog: Catalog) -> NotesDraft:
    fragments = {f.id: f for f in fragments_of(council, group_of(council, group))}
    notes, vanished, numbers, skipped = drafted(stream, fragments, catalog, root, stream.notes,
                                                words_for(language()))
    return NotesDraft(state="running", run=uuid4().hex[:8], issues=cut(stream),
                      language=notes_language(), steps=translating(council.judge), notes=notes,
                      vanished=vanished, numbers=numbers, skipped=skipped)


def drafting(group: str):
    return stream_slot(group, "notes_draft")


@router.post("/{council_id}/streams/{group}/notes/draft", status_code=202,
             responses={**NOT_FOUND, **NOT_THESE_GROUPS, **NO_STREAM, **CHANGING,
                        409: {"description": "Задачи не нарезаны, черновик уже собирается или "
                                             "группы уже другие"},
                        422: {"description": "Каталог заметок не задан или его не прочитать"}})
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
        draft = draft_of(council, group, stream, root, catalog)
        runs: list[CouncilRun] = []
        if not translate or not untranslated(draft.notes):
            draft = draft.model_copy(update={"state": "done", "steps": []})
        elif missing:
            draft = unconnected(draft, missing)
        else:
            runs = [NotesRun(council.id, draft, stream.notes, catalog, root, council.judge,
                             agents, reporter(store, council.id, drafting(group)))]
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
                notes: NotesDep) -> Council:
    """Записывает черновик, который человек смотрел: с его правками текста и удалением
    отмеченных исчезнувших заметок. Файл, правленный руками после прошлой выгрузки, не
    трогается. Каталог поменялся, пока смотрели черновик, — 409: номера могли занять."""
    root = root_of(notes)
    with council_lock:
        council = current(council_id, store, edit)
        stream = stream_in(council, group)
        draft = checked_draft(stream, edit)
        catalog = catalog_of(root)
        fragments = {f.id: f for f in fragments_of(council, group_of(council, group))}
        fresh, vanished, numbers, _ = drafted(stream, fragments, catalog, root, stream.notes,
                                        words_for(language()))
        if (shape(fresh) != shape(draft.notes)
                or [(n.key, n.id) for n in numbers] != [(n.key, n.id) for n in draft.numbers]
                or [v.id for v in vanished] != [v.id for v in draft.vanished]):
            raise HTTPException(409, "Каталог заметок поменялся, пока смотрели черновик, — "
                                     "соберите его заново")
        before = {note.key: note for note in stream.notes.notes} if stream.notes else {}
        planned = [settled(note, before.get(note.key), catalog, root) for note in draft.notes]
        try:
            graph_problems(catalog, planned, vanished, edit.edits, edit.delete)
            exported = written(planned, vanished, edit.edits, edit.delete, root, stream.notes)
        except NotesError as exc:
            raise HTTPException(422, str(exc)) from None
        record = NotesExport(run=draft.run, issues=draft.issues, language=draft.language,
                             notes=exported, numbers=draft.numbers)
        council = store.update_council(council_id, {"streams": replaced(
            council, stream.model_copy(update={"notes": record}))})
    if council is None:
        raise HTTPException(404, MISSING)
    return council


def checked_draft(stream: Stream, edit: WriteNotes) -> NotesDraft:
    draft = stream.notes_draft
    if draft is None or draft.run != edit.draft:
        raise HTTPException(409, "Черновик уже другой — посмотрите на нынешний")
    if draft.state != "done":
        raise HTTPException(409, "Черновик ещё не готов или не собрался — соберите заново")
    if stream.issues is None or draft.issues != stream.issues.run:
        raise HTTPException(409, "Задачи нарезали заново — соберите черновик заново")
    return draft


def shape(notes: Sequence[NotePlan]) -> list[tuple[str, str, list[str], str]]:
    """Что совет выгрузил бы: номера, связи и тексты — в итогах и номера задач, их тоже
    раздают по каталогу."""
    return [(note.key, note.id, note.links, note.generated) for note in notes]
