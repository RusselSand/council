"""Готовые группы: буквы и правки человека — объединить, разделить, переименовать, вернуть
как предложил совет. Без ввода-вывода: к той ли раскладке правка, проверяет API.

Буквы правки не переставляют: у объединённой группы — буква той, где нажали, у новой — первая
свободная. Порядок на экране — по первому фрагменту.
"""

from collections.abc import Iterable
from itertools import count
from string import ascii_uppercase
from typing import Any

from .models import Group, GroupRelation, Structure

TITLE_MAX = 200


class EditRefused(ValueError):
    """Правка без смысла: нет такой группы, делить нечего, название пустое. Для человека — 422."""


def letter_for(n: int) -> str:
    """A…Z, потом A2, B2…: групп больше 26 не ждём, но и падать не должны."""
    letter = ascii_uppercase[n % len(ascii_uppercase)]
    return letter if n < len(ascii_uppercase) else f"{letter}{n // len(ascii_uppercase) + 1}"


def merged(structure: Structure, group_id: str, other_id: str) -> dict[str, Any]:
    """Две группы в одну. Остаётся group — с буквой и названием; связь между ними исчезает,
    связи other переходят к ней. Разошлись связи с одной и той же группой — остаётся связь
    group: там человек и нажал."""
    group, other = group_in(structure, group_id), group_in(structure, other_id)
    if group.id == other.id:
        raise EditRefused("Группу не объединить с самой собой")
    ideas = sorted({*group.idea_fragment_ids, *other.idea_fragment_ids})
    union = group.model_copy(update={
        "fragment_ids": sorted({*group.fragment_ids, *other.fragment_ids}),
        "idea_fragment_ids": ideas, "missing_idea": not ideas,
    })
    groups = [union if g.id == group.id else g for g in structure.groups if g.id != other.id]
    # Сначала связи без other: при расхождении останутся они.
    ordered = sorted(structure.relations, key=lambda r: other.id in (r.source, r.target))
    moved = (r.model_copy(update={"source": group.id if r.source == other.id else r.source,
                                  "target": group.id if r.target == other.id else r.target})
             for r in ordered)
    return {"groups": arranged(groups), "relations": one_per_pair(moved)}


def split(structure: Structure, group_id: str, fragment_ids: Iterable[int],
          title: str) -> dict[str, Any]:
    """Отмеченные фрагменты — в новую группу. Связи остаются у прежней: к новой их никто не
    проводил. Общий фрагмент так и остаётся общим — теперь с новой группой."""
    group = group_in(structure, group_id)
    moving = set(fragment_ids)
    if not moving:
        raise EditRefused("Отметьте, что уходит в новую группу")
    alien = sorted(moving - set(group.fragment_ids))
    if alien:
        raise EditRefused(f"В группе {group.id} нет {', '.join(f'F{i}' for i in alien)}")
    staying = [i for i in group.fragment_ids if i not in moving]
    if not staying:
        raise EditRefused("В группе должно что-то остаться — иначе это переименование")
    ideas = [i for i in group.idea_fragment_ids if i in moving]
    new = Group(id=free_letter(structure.groups), title=title_of(title),
                fragment_ids=sorted(moving), idea_fragment_ids=ideas, missing_idea=not ideas)
    left = [i for i in group.idea_fragment_ids if i not in moving]
    rest = group.model_copy(update={"fragment_ids": staying, "idea_fragment_ids": left,
                                    "missing_idea": not left})
    return {"groups": arranged([*(rest if g.id == group.id else g for g in structure.groups),
                                new])}


def renamed(structure: Structure, group_id: str, title: str) -> dict[str, Any]:
    group = group_in(structure, group_id)
    named = group.model_copy(update={"title": title_of(title)})
    return {"groups": [named if g.id == group.id else g for g in structure.groups]}


def restored(structure: Structure) -> dict[str, Any]:
    """Как предложил совет: правки человека отменяются."""
    if structure.proposal is None:
        raise EditRefused("Предложения совета нет — возвращаться не к чему")
    return {"groups": structure.proposal.groups, "relations": structure.proposal.relations}


def group_in(structure: Structure, group_id: str) -> Group:
    found = next((group for group in structure.groups if group.id == group_id), None)
    if found is None:
        raise EditRefused(f"Нет группы {group_id}")
    return found


def title_of(title: str) -> str:
    title = title.strip()
    if not title:
        raise EditRefused("Нужно название группы")
    if len(title) > TITLE_MAX:
        raise EditRefused(f"Название длиннее {TITLE_MAX} знаков")
    return title


def free_letter(groups: list[Group]) -> str:
    used = {group.id for group in groups}
    return next(letter for letter in map(letter_for, count()) if letter not in used)


def arranged(groups: list[Group]) -> list[Group]:
    """Группы по порядку первого фрагмента, общие фрагменты отмечены заново. Две группы с
    одним составом — одна и та же группа дважды: такую правку не принимаем."""
    seen: set[int] = set()
    twice: set[int] = set()
    kinds: dict[frozenset[int], str] = {}
    for group in groups:
        members = frozenset(group.fragment_ids)
        if members in kinds:
            raise EditRefused(f"Группы {kinds[members]} и {group.id} совпали бы по составу")
        kinds[members] = group.id
        twice |= seen & members
        seen |= members
    marked = (group.model_copy(update={
        "shared_fragment_ids": sorted(twice & set(group.fragment_ids))}) for group in groups)
    return sorted(marked, key=lambda group: min(group.fragment_ids))


def one_per_pair(relations: Iterable[GroupRelation]) -> list[GroupRelation]:
    """Одна связь на пару групп — первая; связь группы с самой собой — не связь."""
    pairs: set[frozenset[str]] = set()
    kept = []
    for relation in relations:
        pair = frozenset((relation.source, relation.target))
        if len(pair) == 2 and pair not in pairs:
            pairs.add(pair)
            kept.append(relation)
    return kept
