"""Раскладка фрагментов по группам: разбор ответов моделей, проверка и сведение. Без ввода-вывода.

Раскладки сравниваются по содержанию, а не по буквам и названиям: у двух участников группа A
может быть одной и той же задумкой под разными именами. Одинаковые — если совпадают составы
групп и связи между ними (связь описывается составами групп, а не буквами; у related
направления нет).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .slicing import BadAnswer, JudgeRejected

RELATION_TYPES = ("independent", "depends_on", "related")
Members = frozenset[int]
Link = tuple[Members, Members, str]


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

    def link(self, relation: RelationOption, floating: Members = frozenset()) -> Link:
        """Связь, описанная составами групп (без плавающих фрагментов): так она сравнима между
        вариантами. У related направления нет, поэтому концы идут в одном порядке."""
        source = self.group(relation.source).members - floating
        target = self.group(relation.target).members - floating
        if relation.type == "related" and sorted(target) < sorted(source):
            source, target = target, source
        return source, target, relation.type

    def links(self, floating: Members = frozenset()) -> frozenset[Link]:
        return frozenset(self.link(r, floating) for r in self.relations if r.type != "independent")

    def key(self) -> tuple[frozenset[Members], frozenset[Link]]:
        return frozenset(group.members for group in self.groups), self.links()


@dataclass(frozen=True)
class JudgeDecision:
    issue: str
    decision: str
    reason: str


def ids_of(value: object, known: set[int], what: str) -> Members:
    if not isinstance(value, list) or not all(
            isinstance(i, int) and not isinstance(i, bool) for i in value):
        raise BadAnswer(f"{what}: нужен список номеров фрагментов")
    unknown = sorted(set(value) - known)
    if unknown:
        raise BadAnswer(f"{what}: нет фрагментов {', '.join(map(str, unknown))}")
    return frozenset(value)


def numbers(ids: Members) -> str:
    return ", ".join(f"F{i}" for i in sorted(ids))


def structure_of(data: dict, labels: Mapping[int, str]) -> StructureOption:
    """Одна раскладка: группы и связи. BadAnswer, если фрагмент потерян, номер выдуман, две
    группы одинаковы или связь ведёт к несуществующей группе."""
    raw_groups = data.get("groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise BadAnswer("нет списка groups")
    groups = [group_of(raw, labels) for raw in raw_groups]
    names = [group.id for group in groups]
    if len(set(names)) != len(names):
        raise BadAnswer("две группы с одним id")
    if len({group.members for group in groups}) != len(groups):
        raise BadAnswer("две группы с одинаковым составом")
    lost = sorted(set(labels) - set().union(*(group.members for group in groups)))
    if lost:
        raise BadAnswer(f"фрагменты не попали ни в одну группу: {', '.join(map(str, lost))}")

    raw_relations = data.get("relations") or []
    if not isinstance(raw_relations, list):
        raise BadAnswer("relations — не список")
    relations = unique_relations(relation_of(raw, names) for raw in raw_relations)
    reason = data.get("reason")
    return StructureOption(tuple(groups), relations,
                           reason if isinstance(reason, str) and reason else None)


def group_of(raw: object, labels: Mapping[int, str]) -> GroupOption:
    """Группа из ответа. Её идеи — фрагменты с типом idea: типы даны и не меняются, поэтому
    idea_fragment_ids и missing_idea модели не нужны — их не проверить лучше, чем вычислить."""
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"].strip():
        raise BadAnswer(f"у группы нет id: {raw!r}"[:200])
    name = raw["id"].strip()
    known = set(labels)
    members = (ids_of(raw.get("fragment_ids"), known, f"группа {name}")
               | ids_of(raw.get("shared_fragment_ids", []), known, f"группа {name}, общие"))
    if not members:
        raise BadAnswer(f"группа {name} пустая")
    title = raw.get("title")
    return GroupOption(name, title.strip() if isinstance(title, str) else "", members,
                       frozenset(i for i in members if labels[i] == "idea"))


def relation_of(raw: object, names: list[str]) -> RelationOption:
    if not isinstance(raw, dict):
        raise BadAnswer(f"связь — не объект: {raw!r}"[:200])
    source, target, kind = raw.get("from"), raw.get("to"), raw.get("type")
    if source not in names or target not in names or source == target:
        raise BadAnswer(f"связь между несуществующими группами: {source!r} → {target!r}")
    if kind not in RELATION_TYPES:
        raise BadAnswer(f"тип связи не из {', '.join(RELATION_TYPES)}: {kind!r}")
    reason = raw.get("reason")
    return RelationOption(source, target, kind, reason if isinstance(reason, str) else "")


def structure_options(data: dict, labels: Mapping[int, str]) -> list[StructureOption]:
    """Раскладки участника. Негодная отбрасывается, но если не годится ни одна — ответ негодный."""
    options = data.get("options")
    if not isinstance(options, list) or not options:
        raise BadAnswer("нет списка options")
    valid, problems = [], []
    for option in options:
        try:
            if not isinstance(option, dict):
                raise BadAnswer("вариант — не объект")
            valid.append(structure_of(option, labels))
        except BadAnswer as exc:
            problems.append(str(exc))
    if not valid:
        raise BadAnswer(problems[0])
    return valid


def judged_structure(data: dict, labels: Mapping[int, str], candidates: list[StructureOption],
                     ) -> tuple[StructureOption, list[JudgeDecision]]:
    """Итог судьи. Он может собрать раскладку из решений разных вариантов, но решает только
    спорное: каждое место фрагмента в группе и каждая связь должны быть хоть в одном варианте,
    а то, в чём сошлись все варианты, остаётся как есть."""
    status = data.get("status")
    if status == "no_valid_option":
        problem = data.get("problem")
        raise JudgeRejected(f"не принял ни один вариант: {problem or 'без объяснения'}; "
                            "повтор спросит участников заново")
    if status != "ok":
        raise BadAnswer(f"неизвестный status: {status!r}")
    option = structure_of(data, labels)
    if candidates:
        floating = option.shared().union(*(candidate.shared() for candidate in candidates))
        check_groups(option, candidates, floating)
        check_links(option, candidates, floating)
    return option, decisions_of(data)


def check_groups(option: StructureOption, candidates: list[StructureOption],
                 floating: Members) -> None:
    """Группа узнаётся между вариантами по собственным фрагментам — без плавающих, то есть
    общих хоть в одном варианте или в итоге: где им стоять, и есть предмет спора. Фрагмент,
    которого нет ни в одном составе группы, судья добавить не может, а тот, что есть во всех, —
    убрать. Группу из одних плавающих узнать не по чему: она должна совпасть с какой-то целиком."""
    versions: dict[Members, list[Members]] = {}
    for candidate in candidates:
        for group in candidate.groups:
            versions.setdefault(group.members - floating, []).append(group.members)
    for group in option.groups:
        own = group.members - floating
        seen = versions.get(own, [])
        if not seen or (not own and group.members not in seen):
            raise BadAnswer(f"судья собрал группу, которой нет ни в одном варианте: "
                            f"{numbers(group.members)}")
        added = group.members - frozenset().union(*seen)
        if added:
            raise BadAnswer(f"судья поместил {numbers(added)} в группу {group.id}, "
                            "куда их не помещал ни один вариант")
        dropped = frozenset.intersection(*seen) - group.members
        if dropped:
            raise BadAnswer(f"судья убрал {numbers(dropped)} из группы {group.id}, "
                            "хотя там их ставили все варианты")


def check_links(option: StructureOption, candidates: list[StructureOption],
                floating: Members) -> None:
    """Связь судьи должна быть хоть в одном варианте, а связь из всех вариантов — в итоге."""
    known = [candidate.links(floating) for candidate in candidates]
    for relation in option.relations:
        if relation.type == "independent":
            continue
        if not any(option.link(relation, floating) in links for links in known):
            raise BadAnswer(f"судья придумал связь {relation.source} → {relation.target} "
                            f"({relation.type})")
    if frozenset.intersection(*known) - option.links(floating):
        raise BadAnswer("судья убрал связь, которая есть во всех вариантах")


def unique_relations(relations: Iterable[RelationOption]) -> tuple[RelationOption, ...]:
    """Одна связь на пару групп. Повтор той же связи просто отбрасывается, две разные —
    противоречие: «зависит» и «связана», или зависимость в обе стороны."""
    kept: dict[frozenset[str], RelationOption] = {}
    for relation in relations:
        pair = frozenset((relation.source, relation.target))
        known = kept.setdefault(pair, relation)
        same = known.type == relation.type and (
            relation.type != "depends_on" or known.source == relation.source)
        if not same:
            raise BadAnswer(f"две разные связи между {relation.source} и {relation.target}")
    return tuple(kept.values())


def decisions_of(data: dict) -> list[JudgeDecision]:
    """Пояснения судьи. Не обязательны: кривая запись пропускается, а не роняет итог."""
    raw = data.get("decisions")
    decisions = []
    for item in raw if isinstance(raw, list) else []:
        fields = ("issue", "decision", "reason")
        if isinstance(item, dict) and all(isinstance(item.get(k), str) for k in fields):
            decisions.append(JudgeDecision(*(item[k].strip() for k in fields)))
    return decisions
