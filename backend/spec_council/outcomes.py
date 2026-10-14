"""Итоги потока: разбор ответов участников и судьи, проверка ссылок. Без ввода-вывода.

Итог стоит на принятых решениях (ADR-n — решение по n-му вопросу отбора), соблюдает
ограничения группы и блокируется открытыми вопросами — теми, по которым решения нет. Ссылки
вторичны: чужой номер просто отбрасывается, а итог остаётся. Блокировать может только открытый
вопрос: решённый уже не держит. Пробел — неопределённость, которой нет среди вопросов: пробел,
совпавший с открытым вопросом отбора, — блокировка им, с решённым — уже ответ. Список итогов
может быть и пустым: фиктивный итог хуже.

Закреплённые итоги (готовые, с теми же решениями) модели не возвращают: если новое решение их
задевает, они говорят об этом в touches — какой итог, какие решения и почему. Пометка — только про
закреплённый итог и только с решениями, которых в нём нет: остальное отбрасывается.

Итог реализует решения (adr_ids) и опирается на решения (relies_on_adr_ids). Реализуемые
раскладываются по итогам: каждое принятое решение реализует ровно один итог (новый или
закреплённый) или его называет пометка о закреплённом. Решение, которое не реализует ни один итог
или реализуют два, — негодный ответ. Опираться на решение может сколько угодно итогов: так итог,
который зависит от решения другого итога, его не теряет. На каждое реализуемое решение у итога
есть строка — что именно из него следует в его поведении (adr_notes); без неё итог негодный: по
этим строкам видно, если решение приписали не тому итогу. Итог ссылается и на прошлые решения
проекта, на которые опирается его поведение (project_decision_ids): номер — из отобранных для
потока, чужой отбрасывается.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from .ideas import reason_of
from .proposals import fragments_in, questions_in
from .questions import QUESTION_MAX, same_question
from .slicing import BadAnswer

TITLE_MAX = 200
BEHAVIOR_MAX = 2000
CRITERION_MAX = 600
NOTE_MAX = 600
ADR_ID = re.compile(r"ADR[-\s]?(\d+)", re.IGNORECASE)
# Номер решения проекта из каталога заметок: «ADR-0007»; без нулей — то же решение.
PROJECT_ID = re.compile(r"\s*([A-Za-z]+)-0*(\d+)\s*")


@dataclass(frozen=True)
class Context:
    """На что итог может сослаться: принятые решения, ограничения и риски группы, открытые
    вопросы потока."""

    adrs: frozenset[str]
    constraints: frozenset[int]
    risks: frozenset[int]
    open_questions: frozenset[str]
    # Вопросы отбора: текст, как его сравнивает same_question, — номер.
    questions: Mapping[str, str] = field(default_factory=dict)
    # Закреплённые итоги: номер — решения, на которых он стоит.
    kept: Mapping[str, frozenset[str]] = field(default_factory=dict)
    # Прошлые решения проекта, отобранные для потока: их номера из каталога.
    project_decisions: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Touch:
    """Новые решения задевают закреплённый итог."""

    outcome_id: str
    adr_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Assembly:
    """Ответ сборки: новые итоги и какие закреплённые задевают новые решения."""

    outcomes: tuple[Candidate, ...]
    touches: tuple[Touch, ...] = ()


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
    # Прошлые решения проекта, на которые опирается его поведение.
    project_decision_ids: tuple[str, ...] = ()
    # Решения потока, которые реализуют другие итоги, а этот на них опирается.
    relies_on: tuple[str, ...] = ()
    # На каждое реализуемое решение — что из него следует в поведении итога: (ADR, строка).
    notes: tuple[tuple[str, str], ...] = ()


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


def project_decisions_in(value: object, allowed: frozenset[str]) -> tuple[str, ...]:
    """Номера решений проекта из ответа — как в каталоге; «ADR-7» — то же, что «ADR-0007».
    Чужой номер отбрасывается."""
    def key(text: str) -> tuple[str, int] | None:
        found = PROJECT_ID.fullmatch(text)
        return (found.group(1).upper(), int(found.group(2))) if found else None
    known = {key(name): name for name in allowed if key(name) is not None}
    items = value if isinstance(value, list) else []
    found = (known.get(key(item)) for item in items if isinstance(item, str))
    return tuple(sorted({name for name in found if name is not None}))


def notes_of(value: object, adrs: tuple[str, ...], what: str) -> tuple[tuple[str, str], ...]:
    """Строки «что следует из решения» — по одной на каждое реализуемое решение; строки к чужим
    решениям отбрасываются. Нет строки к реализуемому решению — итог негодный: номер без
    объяснения не показывает, то ли решение приписали этому итогу."""
    given = value if isinstance(value, dict) else {}
    found: dict[str, str] = {}
    for key, text in given.items():
        match = ADR_ID.fullmatch(key.strip()) if isinstance(key, str) else None
        line = reason_of(text)
        if match and line and len(line) <= NOTE_MAX:
            found.setdefault(f"ADR-{int(match.group(1))}", line)
    missing = [adr for adr in adrs if adr not in found]
    if missing:
        raise BadAnswer(f"{what}: не сказано, что следует из {', '.join(missing)}")
    return tuple((adr, found[adr]) for adr in adrs)


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
    blocked = set(questions_in(item.get("blocked_by"), context.open_questions))
    gaps = []
    for gap in gaps_of(item.get("gaps")):
        known = context.questions.get(same_question(gap.question))
        if known is None:
            gaps.append(gap)
        elif known in context.open_questions:
            blocked.add(known)   # «пробел» — открытый вопрос отбора: он итог и держит
    adrs = adrs_in(item.get("adr_ids"), context.adrs)
    return Candidate(
        text_of(item.get("title"), TITLE_MAX, f"{what}, title"),
        text_of(item.get("behavior"), BEHAVIOR_MAX, f"{what}, behavior"),
        adrs,
        fragments_in(item.get("constraint_ids"), context.constraints),
        fragments_in(item.get("risk_ids"), context.risks),
        criteria_of(item.get("acceptance_criteria")),
        tuple(sorted(blocked)), tuple(gaps),
        project_decisions_in(item.get("project_decision_ids"), context.project_decisions),
        tuple(adr for adr in adrs_in(item.get("relies_on_adr_ids"), context.adrs)
              if adr not in adrs),
        notes_of(item.get("adr_notes"), adrs, what))


def outcome_list(data: dict, context: Context) -> list[Candidate]:
    """Итоги из ответа участника или судьи. Негодный итог отбрасывается, но если не годится
    ни один — ответ негодный. Пустой список — честное «итогов из этих решений не собрать»."""
    return list(assembly_of(data, context).outcomes)


def assembly_of(data: dict, context: Context) -> Assembly:
    """Ответ сборки целиком: итоги (как outcome_list) и пометки о закреплённых итогах."""
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
    assembly = Assembly(tuple(valid), touches_of(data.get("touches"), context))
    spread(assembly, context)
    return assembly


def spread(assembly: Assembly, context: Context) -> None:
    """Каждое принятое решение реализует ровно один итог — новый или закреплённый, — или его
    называет пометка о закреплённом итоге, который оно задевает. Решение, которое реализуют два
    итога или ни один, — негодный ответ; опираться на него (relies_on) могут сколько угодно.
    Закреплённые итоги между собой не сверяются: их уже утверждали."""
    owner: dict[str, str] = {adr: name for name, adrs in context.kept.items() for adr in adrs}
    twice: set[str] = set()
    for n, outcome in enumerate(assembly.outcomes, 1):
        for adr in outcome.adr_ids:
            if adr in owner:
                twice.add(adr)
            owner[adr] = f"итог {n}"
    if twice:
        raise BadAnswer(f"решения реализуют два итога: {', '.join(by_number(twice))}")
    touched = {adr for touch in assembly.touches for adr in touch.adr_ids}
    missing = context.adrs - set(owner) - touched
    if missing:
        raise BadAnswer(f"решения не реализует ни один итог: {', '.join(by_number(missing))}")


def by_number(adrs: set[str] | frozenset[str]) -> list[str]:
    return sorted(adrs, key=lambda name: int(name.split("-")[1]))


def touches_of(value: object, context: Context) -> tuple[Touch, ...]:
    """Пометки: закреплённый итог и решения, которых в нём нет, — те, что его задевают. Чужой
    итог или ни одного нового решения — не пометка. Один итог дважды — одна пометка."""
    found: dict[str, Touch] = {}
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("outcome_id") or "").strip().upper()
        if name not in context.kept:
            continue
        adrs = tuple(adr for adr in adrs_in(item.get("adr_ids"), context.adrs)
                     if adr not in context.kept[name])
        if not adrs:
            continue
        before = found.get(name)
        reason = reason_of(item.get("reason"))
        if before is not None:
            adrs = tuple(sorted({*before.adr_ids, *adrs}, key=lambda a: int(a.split("-")[1])))
            reason = "; ".join(text for text in dict.fromkeys((before.reason, reason)) if text)
        found[name] = Touch(name, adrs, reason)
    return tuple(found[name] for name in sorted(found, key=lambda n: int(n[1:])))


def as_prompt(candidate: Candidate) -> dict:
    """Итог для судьи — в той же форме, в какой его просили у участников."""
    return {"title": candidate.title, "behavior": candidate.behavior,
            "adr_ids": list(candidate.adr_ids),
            "adr_notes": dict(candidate.notes),
            "relies_on_adr_ids": list(candidate.relies_on),
            "project_decision_ids": list(candidate.project_decision_ids),
            "constraint_ids": [f"F{i}" for i in candidate.constraint_ids],
            "risk_ids": [f"F{i}" for i in candidate.risk_ids],
            "acceptance_criteria": list(candidate.criteria),
            "blocked_by": list(candidate.blocked_by),
            "gaps": [{"question": gap.question, "reason": gap.reason} for gap in candidate.gaps]}


def same_assembly(assembly: Assembly) -> str:
    """Ответ сборки для сравнения: итоги (как same_outcomes) и какие закреплённые задеты —
    разошлись в этом, значит, разошлись."""
    touched = sorted([touch.outcome_id, list(touch.adr_ids)] for touch in assembly.touches)
    return json.dumps([same_outcomes(list(assembly.outcomes)), touched], ensure_ascii=False)


def touch_prompt(touch: Touch) -> dict:
    return {"outcome_id": touch.outcome_id, "adr_ids": list(touch.adr_ids), "reason": touch.reason}


def same_outcomes(candidates: list[Candidate]) -> str:
    """Набор итогов для сравнения: порядок итогов, их критериев и пробелов модели не держат —
    одинаковые наборы в разном порядке — один набор."""
    def one(candidate: Candidate) -> str:
        data = as_prompt(candidate)
        data["acceptance_criteria"] = sorted(data["acceptance_criteria"])
        data["gaps"] = sorted(data["gaps"], key=lambda gap: (gap["question"], gap["reason"]))
        return json.dumps(data, ensure_ascii=False, sort_keys=True)
    return json.dumps(sorted(one(candidate) for candidate in candidates), ensure_ascii=False)
