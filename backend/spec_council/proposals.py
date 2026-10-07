"""Варианты ответа на открытый вопрос: разбор ответов моделей, проверка и сведение. Без
ввода-вывода.

Вариант — один возможный ответ, а не решение. Его ссылки — на ограничения и риски группы и
на другие вопросы потока, от которых он зависит. Ссылки вторичны: чужой или не тот номер
просто отбрасывается, а сам вариант остаётся. Одинаковые варианты разных участников — один.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from .ideas import fragment_number, reason_of
from .questions import same_question
from .slicing import BadAnswer

PROPOSAL_MAX = 600
VERDICTS = {"recommended": "recommended", "alternatives": "alternatives",
            "no_recommendation": "none"}


@dataclass(frozen=True)
class Context:
    """На что вариант может сослаться: ограничения и риски группы, другие вопросы потока."""

    constraints: frozenset[int]
    risks: frozenset[int]
    questions: frozenset[str]


@dataclass(frozen=True)
class Candidate:
    text: str
    reason: str
    constraint_ids: tuple[int, ...]
    risk_ids: tuple[int, ...]
    depends_on: tuple[str, ...]


@dataclass(frozen=True)
class Verdict:
    """Решение судьи: recommended — один предпочтительный, alternatives — равноправные, none —
    новых обоснованных вариантов нет. reason — чем различаются альтернативы или почему нет."""

    kind: str
    proposals: tuple[Candidate, ...]
    reason: str | None


def proposal_text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BadAnswer(f"{what}: нет текста варианта")
    text = " ".join(value.split())
    if len(text) > PROPOSAL_MAX:
        raise BadAnswer(f"{what}: вариант длиннее {PROPOSAL_MAX} знаков")
    return text


def fragments_in(value: object, allowed: frozenset[int]) -> tuple[int, ...]:
    numbers = (fragment_number(item) for item in value) if isinstance(value, list) else ()
    return tuple(sorted({n for n in numbers if n is not None and n in allowed}))


def questions_in(value: object, allowed: frozenset[str]) -> tuple[str, ...]:
    names = (item.strip().upper() for item in value
             if isinstance(item, str)) if isinstance(value, list) else ()
    return tuple(sorted({name for name in names if name in allowed}))


def candidate_of(item: object, context: Context, what: str) -> Candidate:
    if not isinstance(item, dict):
        raise BadAnswer(f"{what} — не объект")
    return Candidate(proposal_text(item.get("text"), what), reason_of(item.get("reason")),
                     fragments_in(item.get("constraint_ids"), context.constraints),
                     fragments_in(item.get("risk_ids"), context.risks),
                     questions_in(item.get("depends_on_question_ids"), context.questions))


def candidates_of(raw: object, context: Context, what: str) -> list[Candidate]:
    """Варианты из списка. Негодный отбрасывается, но если не годится ни один — ответ негодный.
    Пустой список — честное «новых вариантов нет»."""
    if not isinstance(raw, list):
        raise BadAnswer(f"{what}: нет списка proposals")
    valid, problems = [], []
    for n, item in enumerate(raw, 1):
        try:
            valid.append(candidate_of(item, context, f"вариант {n}"))
        except BadAnswer as exc:
            problems.append(str(exc))
    if problems and not valid:
        raise BadAnswer(problems[0])
    return merged(valid)


def proposal_list(data: dict, context: Context) -> list[Candidate]:
    """Новые варианты участника."""
    return candidates_of(data.get("proposals"), context, "ответ")


def judged_proposals(data: dict, context: Context) -> Verdict:
    """Итог судьи. Он может свести формулировки участников, поэтому текст не обязан совпасть
    ни с одной; ссылки — только на то, что есть в потоке."""
    status = data.get("status")
    kind = VERDICTS.get(status) if isinstance(status, str) else None
    if kind is None:
        raise BadAnswer(f"неизвестный status: {status!r}")
    reason = reason_of(data.get("reason")) or None
    if kind == "none":
        return Verdict("none", (), reason)
    if kind == "recommended":
        return Verdict("recommended", (candidate_of(data.get("proposal"), context, "судья"),),
                       reason)
    found = candidates_of(data.get("proposals"), context, "судья")
    if not found:
        raise BadAnswer("судья: alternatives без вариантов")
    return Verdict("alternatives", tuple(found), reason)


def merged(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Одинаковые варианты — один: формулировка и пояснение первого, ссылки — все."""
    found: dict[str, Candidate] = {}
    for candidate in candidates:
        key = same_question(candidate.text)
        known = found.get(key)
        found[key] = candidate if known is None else Candidate(
            known.text, known.reason,
            tuple(sorted({*known.constraint_ids, *candidate.constraint_ids})),
            tuple(sorted({*known.risk_ids, *candidate.risk_ids})),
            tuple(sorted({*known.depends_on, *candidate.depends_on})))
    return list(found.values())


def as_prompt(candidate: Candidate) -> dict:
    """Вариант для судьи — в той же форме, в какой его просили у участников."""
    return {"text": candidate.text, "reason": candidate.reason,
            "constraint_ids": [f"F{i}" for i in candidate.constraint_ids],
            "risk_ids": [f"F{i}" for i in candidate.risk_ids],
            "depends_on_question_ids": list(candidate.depends_on)}
