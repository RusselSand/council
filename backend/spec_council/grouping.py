"""Раскладка фрагментов по группам: разбор ответов моделей, проверка и сведение. Без ввода-вывода.

Раскладки сравниваются по содержанию, а не по буквам и названиям: у двух участников группа A
может быть одной и той же задумкой под разными именами. Одинаковые — если совпадают составы
групп и связи между ними (связь описывается составами групп, а не буквами).
"""

from dataclasses import dataclass

from .slicing import BadAnswer, JudgeRejected

RELATION_TYPES = ("independent", "depends_on", "related")
Members = frozenset[int]


@dataclass(frozen=True)
class GroupOption:
    id: str
    title: str
    members: Members
    ideas: Members


@dataclass(frozen=True)
class RelationOption:
    source: str
    target: str
    type: str
    reason: str


@dataclass(frozen=True)
class StructureOption:
    groups: tuple[GroupOption, ...]
    relations: tuple[RelationOption, ...]
    reason: str | None

    def group(self, group_id: str) -> GroupOption:
        return next(group for group in self.groups if group.id == group_id)

    def shared(self) -> Members:
        """Фрагменты, которые стоят больше чем в одной группе."""
        seen: set[int] = set()
        twice: set[int] = set()
        for group in self.groups:
            twice |= seen & group.members
            seen |= group.members
        return frozenset(twice)

    def core(self, group: GroupOption) -> Members:
        """Собственные фрагменты группы — без общих. По ним группы узнаются между вариантами:
        судья может отдать общее ограничение ещё одной группе, но не пересобрать группу."""
        return group.members - self.shared()

    def links(self) -> frozenset[tuple[Members, Members, str]]:
        """Связи, описанные составами групп: так они сравнимы между вариантами."""
        return frozenset((self.group(r.source).members, self.group(r.target).members, r.type)
                         for r in self.relations if r.type != "independent")

    def key(self) -> tuple[frozenset[Members], frozenset[tuple[Members, Members, str]]]:
        return frozenset(group.members for group in self.groups), self.links()


@dataclass(frozen=True)
class Decision:
    issue: str
    decision: str
    reason: str


def ids_of(value: object, known: set[int], what: str) -> Members:
    numbers = isinstance(value, list) and all(
        isinstance(i, int) and not isinstance(i, bool) for i in value)
    if not numbers:
        raise BadAnswer(f"{what}: нужен список номеров фрагментов")
    unknown = sorted(set(value) - known)
    if unknown:
        raise BadAnswer(f"{what}: нет фрагментов {', '.join(map(str, unknown))}")
    return frozenset(value)


def structure_of(data: dict, ids: list[int]) -> StructureOption:
    """Одна раскладка: группы и связи. BadAnswer, если фрагмент потерян, номер выдуман или
    связь ведёт к несуществующей группе."""
    known = set(ids)
    raw_groups = data.get("groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise BadAnswer("нет списка groups")
    groups = []
    for raw in raw_groups:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"].strip():
            raise BadAnswer(f"у группы нет id: {raw!r}"[:200])
        name = raw["id"].strip()
        title = raw.get("title")
        members = (ids_of(raw.get("fragment_ids"), known, f"группа {name}")
                   | ids_of(raw.get("shared_fragment_ids", []), known, f"группа {name}, общие"))
        if not members:
            raise BadAnswer(f"группа {name} пустая")
        ideas = ids_of(raw.get("idea_fragment_ids", []), known, f"группа {name}, идеи") & members
        title = title.strip() if isinstance(title, str) else ""
        groups.append(GroupOption(name, title, members, ideas))
    names = [group.id for group in groups]
    if len(set(names)) != len(names):
        raise BadAnswer("две группы с одним id")
    lost = sorted(known - set().union(*(group.members for group in groups)))
    if lost:
        raise BadAnswer(f"фрагменты не попали ни в одну группу: {', '.join(map(str, lost))}")

    raw_relations = data.get("relations") or []
    if not isinstance(raw_relations, list):
        raise BadAnswer("relations — не список")
    relations = []
    for raw in raw_relations:
        if not isinstance(raw, dict):
            raise BadAnswer(f"связь — не объект: {raw!r}"[:200])
        source, target, kind = raw.get("from"), raw.get("to"), raw.get("type")
        if source not in names or target not in names or source == target:
            raise BadAnswer(f"связь между несуществующими группами: {source!r} → {target!r}")
        if kind not in RELATION_TYPES:
            raise BadAnswer(f"тип связи не из {', '.join(RELATION_TYPES)}: {kind!r}")
        reason = raw.get("reason")
        reason = reason if isinstance(reason, str) else ""
        relations.append(RelationOption(source, target, kind, reason))
    reason = data.get("reason")
    reason = reason if isinstance(reason, str) and reason else None
    return StructureOption(tuple(groups), tuple(relations), reason)


def structure_options(data: dict, ids: list[int]) -> list[StructureOption]:
    """Раскладки участника. Негодная отбрасывается, но если не годится ни одна — ответ негодный."""
    options = data.get("options")
    if not isinstance(options, list) or not options:
        raise BadAnswer("нет списка options")
    valid, problems = [], []
    for option in options:
        try:
            if not isinstance(option, dict):
                raise BadAnswer("вариант — не объект")
            valid.append(structure_of(option, ids))
        except BadAnswer as exc:
            problems.append(str(exc))
    if not valid:
        raise BadAnswer(problems[0])
    return valid


def judged_structure(data: dict, ids: list[int],
                     candidates: list[StructureOption]) -> tuple[StructureOption, list[Decision]]:
    """Итог судьи. Он может собрать раскладку из решений разных вариантов, но не создать
    группу, которой нет ни в одном (по собственным фрагментам), и не придумать связь."""
    status = data.get("status")
    if status == "no_valid_option":
        problem = data.get("problem")
        raise JudgeRejected(f"не принял ни один вариант: {problem or 'без объяснения'}; "
                            "повтор спросит участников заново")
    if status != "ok":
        raise BadAnswer(f"неизвестный status: {status!r}")
    option = structure_of(data, ids)
    cores = {candidate.core(group) for candidate in candidates for group in candidate.groups}
    for group in option.groups:
        if option.core(group) not in cores:
            numbers = ", ".join(f"F{i}" for i in sorted(group.members))
            raise BadAnswer(f"судья собрал группу, которой нет ни в одном варианте: {numbers}")
    known_links = {link for candidate in candidates for link in core_links(candidate)}
    for relation in option.relations:
        if relation.type == "independent":
            continue
        if core_link(option, relation) not in known_links:
            raise BadAnswer(f"судья придумал связь {relation.source} → {relation.target} "
                            f"({relation.type})")
    return option, decisions_of(data)


def core_link(option: StructureOption, relation: RelationOption) -> tuple[Members, Members, str]:
    """Связь, описанная собственными фрагментами групп: так её узнать в другом варианте."""
    return (option.core(option.group(relation.source)),
            option.core(option.group(relation.target)), relation.type)


def core_links(option: StructureOption) -> set[tuple[Members, Members, str]]:
    return {core_link(option, r) for r in option.relations if r.type != "independent"}


def decisions_of(data: dict) -> list[Decision]:
    """Пояснения судьи. Не обязательны: кривая запись пропускается, а не роняет итог."""
    raw = data.get("decisions")
    decisions = []
    for item in raw if isinstance(raw, list) else []:
        fields = ("issue", "decision", "reason")
        if isinstance(item, dict) and all(isinstance(item.get(k), str) for k in fields):
            decisions.append(Decision(*(item[k].strip() for k in fields)))
    return decisions
