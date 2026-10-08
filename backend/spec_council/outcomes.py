"""Итоги потока: разбор ответов участников и судьи, проверка ссылок. Без ввода-вывода.

Итог стоит на принятых решениях (ADR-n — решение по n-му вопросу отбора), соблюдает
ограничения группы и блокируется открытыми вопросами — теми, по которым решения нет. Ссылки
вторичны: чужой номер просто отбрасывается, а итог остаётся. Блокировать может только открытый
вопрос: решённый уже не держит. Список итогов может быть и пустым: фиктивный итог хуже.
"""

import json
import re
from dataclasses import dataclass

from .ideas import reason_of
from .proposals import fragments_in, questions_in
from .questions import QUESTION_MAX
from .slicing import BadAnswer

TITLE_MAX = 200
BEHAVIOR_MAX = 2000
CRITERION_MAX = 600
ADR_ID = re.compile(r"ADR[-\s]?(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class Context:
    """На что итог может сослаться: принятые решения, ограничения и риски группы, открытые
    вопросы потока."""

    adrs: frozenset[str]
    constraints: frozenset[int]
    risks: frozenset[int]
    open_questions: frozenset[str]


@dataclass(frozen=True)
class Gap:
    question: str
    reason: str


@dataclass(frozen=True)
class Candidate:
    title: str
    behavior: str
    adr_ids: tuple[str, ...]
    constraint_ids: tuple[int, ...]
    risk_ids: tuple[int, ...]
    criteria: tuple[str, ...]
    blocked_by: tuple[str, ...]
    gaps: tuple[Gap, ...]


def text_of(value: object, limit: int, what: str) -> str:
    text = reason_of(value)
    if not text:
        raise BadAnswer(f"{what}: пусто")
    if len(text) > limit:
        raise BadAnswer(f"{what}: длиннее {limit} знаков")
    return text


def adrs_in(value: object, allowed: frozenset[str]) -> tuple[str, ...]:
    found = (ADR_ID.fullmatch(item.strip()) for item in value
             if isinstance(item, str)) if isinstance(value, list) else ()
    names = [f"ADR-{int(match.group(1))}" for match in found if match]
    return tuple(sorted({name for name in names if name in allowed},
                        key=lambda name: int(name.split("-")[1])))


def criteria_of(value: object) -> tuple[str, ...]:
    """Критерии готовности: пустые и слишком длинные отбрасываются, повторы — тоже."""
    texts = (reason_of(item) for item in value) if isinstance(value, list) else ()
    return tuple(dict.fromkeys(text for text in texts if text and len(text) <= CRITERION_MAX))


def gaps_of(value: object) -> tuple[Gap, ...]:
    """Пробелы. Человек добавляет пробел в вопросы, поэтому пустой или длиннее вопроса
    отбрасывается: отбор его не примет."""
    items = value if isinstance(value, list) else []
    return tuple(Gap(reason_of(item.get("question")), reason_of(item.get("reason")))
                 for item in items
                 if isinstance(item, dict)
                 and 0 < len(reason_of(item.get("question"))) <= QUESTION_MAX)


def candidate_of(item: object, context: Context, what: str) -> Candidate:
    if not isinstance(item, dict):
        raise BadAnswer(f"{what} — не объект")
    return Candidate(
        text_of(item.get("title"), TITLE_MAX, f"{what}, title"),
        text_of(item.get("behavior"), BEHAVIOR_MAX, f"{what}, behavior"),
        adrs_in(item.get("adr_ids"), context.adrs),
        fragments_in(item.get("constraint_ids"), context.constraints),
        fragments_in(item.get("risk_ids"), context.risks),
        criteria_of(item.get("acceptance_criteria")),
        questions_in(item.get("blocked_by"), context.open_questions),
        gaps_of(item.get("gaps")))


def outcome_list(data: dict, context: Context) -> list[Candidate]:
    """Итоги из ответа участника или судьи. Негодный итог отбрасывается, но если не годится
    ни один — ответ негодный. Пустой список — честное «итогов из этих решений не собрать»."""
    raw = data.get("outcomes")
    if not isinstance(raw, list):
        raise BadAnswer("нет списка outcomes")
    valid, problems = [], []
    for n, item in enumerate(raw, 1):
        try:
            valid.append(candidate_of(item, context, f"итог {n}"))
        except BadAnswer as exc:
            problems.append(str(exc))
    if problems and not valid:
        raise BadAnswer(problems[0])
    return valid


def as_prompt(candidate: Candidate) -> dict:
    """Итог для судьи — в той же форме, в какой его просили у участников."""
    return {"title": candidate.title, "behavior": candidate.behavior,
            "adr_ids": list(candidate.adr_ids),
            "constraint_ids": [f"F{i}" for i in candidate.constraint_ids],
            "risk_ids": [f"F{i}" for i in candidate.risk_ids],
            "acceptance_criteria": list(candidate.criteria),
            "blocked_by": list(candidate.blocked_by),
            "gaps": [{"question": gap.question, "reason": gap.reason} for gap in candidate.gaps]}


def same_outcomes(candidates: list[Candidate]) -> str:
    """Набор итогов для сравнения: порядок итогов, их критериев и пробелов модели не держат —
    одинаковые наборы в разном порядке — один набор."""
    def one(candidate: Candidate) -> str:
        data = as_prompt(candidate)
        data["acceptance_criteria"] = sorted(data["acceptance_criteria"])
        data["gaps"] = sorted(data["gaps"], key=lambda gap: (gap["question"], gap["reason"]))
        return json.dumps(data, ensure_ascii=False, sort_keys=True)
    return json.dumps(sorted(one(candidate) for candidate in candidates), ensure_ascii=False)
