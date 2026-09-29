"""Правки готовых групп человеком: объединить, разделить, переименовать, вернуть как
предложил совет. Каждая правка привязана к раскладке (run): разложили заново — прежняя
правка уже не про эти группы."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from ..deps import StoreDep
from ..groups import EditRefused, merged, renamed, restored, split
from ..models import Council, GroupsEdit, MergeGroups, RenameGroup, SplitGroup, Structure
from .councils import MISSING, NOT_FOUND, council_lock

router = APIRouter(prefix="/councils", tags=["groups"])

EDIT_RESPONSES = {
    **NOT_FOUND,
    409: {"description": "Группы уже разложили заново или их ещё нет"},
    422: {"description": "Правка без смысла: нет такой группы, делить нечего, пустое название"},
}


@router.post("/{council_id}/structure/merge", responses=EDIT_RESPONSES)
def merge_groups(council_id: str, edit: MergeGroups, store: StoreDep) -> Council:
    """Объединяет две группы. Остаётся group — с её буквой и названием."""
    return edited(council_id, store, edit, lambda s: merged(s, edit.group, edit.other))


@router.post("/{council_id}/structure/split", responses=EDIT_RESPONSES)
def split_group(council_id: str, edit: SplitGroup, store: StoreDep) -> Council:
    """Выносит отмеченные фрагменты группы в новую, под первой свободной буквой."""
    return edited(council_id, store, edit,
                  lambda s: split(s, edit.group, edit.fragment_ids, edit.title))


@router.post("/{council_id}/structure/rename", responses=EDIT_RESPONSES)
def rename_group(council_id: str, edit: RenameGroup, store: StoreDep) -> Council:
    return edited(council_id, store, edit, lambda s: renamed(s, edit.group, edit.title))


@router.post("/{council_id}/structure/restore", responses=EDIT_RESPONSES)
def restore_groups(council_id: str, edit: GroupsEdit, store: StoreDep) -> Council:
    """Отменяет правки человека: группы и связи — как предложил совет."""
    return edited(council_id, store, edit, restored)


def edited(council_id: str, store: StoreDep, edit: GroupsEdit,
           change: Callable[[Structure], dict[str, Any]]) -> Council:
    with council_lock:  # правка и новый запуск раскладки не должны разойтись
        council = store.get_council(council_id)
        if council is None:
            raise HTTPException(404, MISSING)
        structure = council.structure
        if structure is None or structure.state != "done" or structure.run != edit.run:
            raise HTTPException(409, "Группы уже разложили заново — правка была к прежним")
        try:
            changes = change(structure)
        except EditRefused as exc:
            raise HTTPException(422, str(exc)) from exc
        council = store.update_council(
            council_id, {"structure": structure.model_copy(update=changes)})
    if council is None:
        raise HTTPException(404, MISSING)
    return council
