"""Идея группы, которой нет в тексте: разбор ответов моделей, проверка и сведение. Без
ввода-вывода.

Участник может предложить несколько формулировок или ни одной — если честно не видит, как
восстановить идею, не добавив смысла. Одинаковые формулировки разных участников — один
вариант. Опора идеи — фрагменты группы: номер не из группы делает вариант негодным.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .slicing import BadAnswer

IDEA_MAX = 1000
FRAGMENT_ID = re.compile(r"F?(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class IdeaCandidate:
    idea: str
    evidence: tuple[int, ...]
    reason: str


@dataclass(frozen=True)
class IdeaAnswer:
    """Ответ участника: варианты идеи; нет ни одного — reason, почему."""

    options: tuple[IdeaCandidate, ...]
    reason: str


@dataclass(frozen=True)
class IdeaVerdict:
    """Решение судьи. idea None — не принял ни один вариант."""

    idea: str | None
    evidence: tuple[int, ...]
    reason: str


def same_idea(text: str) -> str:
    """Что сравнивать: формулировки, разные только пробелами, регистром или точкой в конце,
    — одна и та же идея."""
    return " ".join(text.split()).rstrip(".").casefold()


def idea_text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BadAnswer(f"{what}: нет текста идеи")
    text = " ".join(value.split())
    if len(text) > IDEA_MAX:
        raise BadAnswer(f"{what}: идея длиннее {IDEA_MAX} знаков")
    return text


def evidence_of(value: object, known: set[int], what: str) -> tuple[int, ...]:
    """Номера фрагментов: «F3» или 3. Пусто или не из группы — вариант негодный."""
    if not isinstance(value, list) or not value:
        raise BadAnswer(f"{what}: нет evidence — на какие фрагменты опирается идея")
    ids = set()
    for item in value:
        found = FRAGMENT_ID.fullmatch(item.strip()) if isinstance(item, str) else None
        if isinstance(item, int) and not isinstance(item, bool):
            ids.add(item)
        elif found:
            ids.add(int(found.group(1)))
        else:
            raise BadAnswer(f"{what}: в evidence не номер фрагмента: {item!r}"[:200])
    alien = sorted(ids - known)
    if alien:
        raise BadAnswer(f"{what}: фрагментов {', '.join(f'F{i}' for i in alien)} нет в группе")
    return tuple(sorted(ids))


def reason_of(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def idea_options(data: dict, known: set[int]) -> IdeaAnswer:
    """Варианты участника. Негодный отбрасывается, но если не годится ни один — ответ
    негодный. Пустой список — честное «не восстановить»."""
    options = data.get("options")
    if not isinstance(options, list):
        raise BadAnswer("нет списка options")
    valid, problems = [], []
    for n, option in enumerate(options, 1):
        try:
            if not isinstance(option, dict):
                raise BadAnswer(f"вариант {n} — не объект")
            valid.append(IdeaCandidate(idea_text(option.get("idea"), f"вариант {n}"),
                                       evidence_of(option.get("evidence"), known, f"вариант {n}"),
                                       reason_of(option.get("reason"))))
        except BadAnswer as exc:
            problems.append(str(exc))
    if problems and not valid:
        raise BadAnswer(problems[0])
    return IdeaAnswer(tuple(valid), reason_of(data.get("reason")))


def judged_idea(data: dict, known: set[int]) -> IdeaVerdict:
    """Итог судьи. Он может свести формулировки кандидатов, поэтому текст не обязан совпасть
    ни с одним; опора — только фрагменты группы. «Не принял ни один» — тоже итог: варианты
    остаются человеку."""
    status = data.get("status")
    if status == "no_valid_option":
        return IdeaVerdict(None, (), reason_of(data.get("reason")) or "без объяснения")
    if status != "ok":
        raise BadAnswer(f"неизвестный status: {status!r}")
    return IdeaVerdict(idea_text(data.get("idea"), "судья"),
                       evidence_of(data.get("evidence"), known, "судья"),
                       reason_of(data.get("reason")))


@dataclass
class MergedOption:
    """Вариант идеи и кто его предложил."""

    idea: str
    evidence: set[int]
    reason: str
    models: list[str]


def merged(answers: dict[str, IdeaAnswer]) -> list[MergedOption]:
    """Варианты всех участников, одинаковые — вместе: формулировка и пояснение первого,
    опора — общая."""
    found: dict[str, MergedOption] = {}
    for model, answer in answers.items():
        for option in answer.options:
            known = found.setdefault(same_idea(option.idea),
                                     MergedOption(option.idea, set(), option.reason, []))
            known.evidence |= set(option.evidence)
            if model not in known.models:
                known.models.append(model)
    return list(found.values())


def declined(answers: dict[str, IdeaAnswer]) -> str:
    """Почему никто не предложил идею: пояснения участников."""
    reasons = [answer.reason for answer in answers.values() if answer.reason]
    return "; ".join(dict.fromkeys(reasons)) or "участники не нашли общей цели группы"


def as_ids(ids: Iterable[int]) -> list[str]:
    """Номера фрагментов так, как их видят модели: F1, F2…"""
    return [f"F{i}" for i in sorted(ids)]
