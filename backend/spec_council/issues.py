"""Задачи потока: разбор ответов участников и судьи, проверка ссылок. Без ввода-вывода.

Задача (issue) реализует часть утверждённых итогов: стоит на них и на принятых решениях,
соблюдает ограничения группы. Ссылки вторичны: чужой номер просто отбрасывается, а задача
остаётся. Но задача без единого утверждённого итога ничего утверждённого не реализует — она
отбрасывается. Зависимости — только на задачи того же ответа, без самой себя и без кругов:
круг — негодный ответ. Номер, который ответ дал двум задачам, — ссылка на неизвестно какую из
них: такие ссылки не берём. Задачу блокирует пробел того же ответа (G-n) или открытый вопрос
потока. Пробел, совпавший с открытым вопросом отбора, — блокировка им, с решённым — уже ответ.
Список задач может быть и пустым: всё уже реализовано или заблокировано.
"""

import itertools
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from .ideas import reason_of
from .outcomes import adrs_in
from .proposals import fragments_in
from .questions import QUESTION_MAX, same_question
from .slicing import BadAnswer

TITLE_MAX = 200
STORY_MAX = 1000
STATE_MAX = 2000
ITEM_MAX = 1000
ISSUE_ID = re.compile(r"I?(\d+)", re.IGNORECASE)
GAP_ID = re.compile(r"G(\d+)", re.IGNORECASE)
OUTCOME_ID = re.compile(r"O?(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class Context:
    """На что задача может сослаться: утверждённые итоги, принятые решения, ограничения и
    риски группы, открытые вопросы потока."""

    outcomes: frozenset[str]
    adrs: frozenset[str]
    constraints: frozenset[int]
    risks: frozenset[int]
    open_questions: frozenset[str]
    # Вопросы отбора: текст, как его сравнивает same_question, — номер.
    questions: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Gap:
    question: str
    reason: str
    outcome_ids: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    # Номер задачи в ответе — на него ссылаются depends_on; "" — номера нет или он повторён.
    name: str
    title: str
    user_story: str
    entry_points: tuple[str, ...]
    current_state: str
    scope: tuple[str, ...]
    outcome_ids: tuple[str, ...]
    adr_ids: tuple[str, ...]
    constraint_ids: tuple[int, ...]
    risk_ids: tuple[int, ...]
    # Номера задач этого ответа (name), результат которых нужен этой.
    depends_on: tuple[str, ...]
    # Открытые вопросы потока и пробелы этого ответа: «G<n>» — n-й из gaps.
    blocked_by: tuple[str, ...]


@dataclass(frozen=True)
class Answer:
    issues: tuple[Candidate, ...]
    gaps: tuple[Gap, ...]


def text_of(value: object, limit: int, what: str) -> str:
    text = reason_of(value)
    if not text:
        raise BadAnswer(f"{what}: пусто")
    if len(text) > limit:
        raise BadAnswer(f"{what}: длиннее {limit} знаков")
    return text


def texts_of(value: object) -> tuple[str, ...]:
    """Пункты списка: пустые и слишком длинные отбрасываются, повторы — тоже."""
    texts = (reason_of(item) for item in value) if isinstance(value, list) else ()
    return tuple(dict.fromkeys(text for text in texts if text and len(text) <= ITEM_MAX))


def outcomes_in(value: object, allowed: frozenset[str]) -> tuple[str, ...]:
    found = (OUTCOME_ID.fullmatch(item.strip()) for item in value
             if isinstance(item, str)) if isinstance(value, list) else ()
    names = {f"O{int(match.group(1))}" for match in found if match}
    return tuple(sorted(names & allowed, key=lambda name: int(name[1:])))


def name_of(value: object) -> str:
    found = ISSUE_ID.fullmatch(value.strip()) if isinstance(value, str) else None
    return f"I{int(found.group(1))}" if found else ""


def gaps_of(value: object, context: Context) -> tuple[list[Gap], dict[int, str]]:
    """Пробелы ответа и куда ведёт ссылка на n-й из них: «G<k>» — на k-й оставшийся, «Q…» — на
    открытый вопрос отбора, с которым он совпал. Пробел, совпавший с решённым вопросом, — уже
    ответ, а пустой или длиннее вопроса отбор не примет: такие отбрасываются."""
    items = value if isinstance(value, list) else []
    kept: list[Gap] = []
    refs: dict[int, str] = {}
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        question = reason_of(item.get("question"))
        if not 0 < len(question) <= QUESTION_MAX:
            continue
        known = context.questions.get(same_question(question))
        if known is not None:
            if known in context.open_questions:
                refs[n] = known
            continue
        kept.append(Gap(question, reason_of(item.get("reason")),
                        outcomes_in(item.get("outcome_ids"), context.outcomes)))
        refs[n] = f"G{len(kept)}"
    return kept, refs


def blocked_of(value: object, context: Context, gaps: list[Gap],
               refs: dict[int, str]) -> tuple[str, ...]:
    """Чем задача заблокирована: открытый вопрос отбора по номеру или тексту, пробел ответа по
    номеру (G-n) или тексту. Остальное — чужие номера: отбрасываются."""
    items = value if isinstance(value, list) else []
    found: set[str] = set()
    texts = {same_question(gap.question): f"G{n}" for n, gap in enumerate(gaps, 1)}
    for item in items:
        if not isinstance(item, str):
            continue
        name = item.strip().upper()
        gap = GAP_ID.fullmatch(name)
        if name in context.open_questions:
            found.add(name)
        elif gap and int(gap.group(1)) in refs:
            found.add(refs[int(gap.group(1))])
        elif (known := context.questions.get(same_question(item))) in context.open_questions:
            found.add(known)
        elif same_question(item) in texts:
            found.add(texts[same_question(item)])
    return tuple(sorted(found))


def candidate_of(item: object, context: Context, gaps: list[Gap], refs: dict[int, str],
                 what: str) -> Candidate:
    if not isinstance(item, dict):
        raise BadAnswer(f"{what} — не объект")
    outcome_ids = outcomes_in(item.get("outcome_ids"), context.outcomes)
    if not outcome_ids:
        raise BadAnswer(f"{what}: ни одного утверждённого итога")
    current = reason_of(item.get("current_state"))
    scope = texts_of(item.get("scope"))
    if not scope:
        raise BadAnswer(f"{what}: нечего делать — scope пуст")
    return Candidate(
        name_of(item.get("id")),
        text_of(item.get("title"), TITLE_MAX, f"{what}, title"),
        text_of(item.get("user_story"), STORY_MAX, f"{what}, user_story"),
        texts_of(item.get("main_entry_points")),
        current if len(current) <= STATE_MAX else "",
        scope,
        outcome_ids,
        adrs_in(item.get("adr_ids"), context.adrs),
        fragments_in(item.get("constraint_ids"), context.constraints),
        fragments_in(item.get("risk_ids"), context.risks),
        tuple(name for name in map(name_of, as_list(item.get("depends_on"))) if name),
        blocked_of(item.get("blocked_by"), context, gaps, refs))


def as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def issue_set(data: dict, context: Context) -> Answer:
    """Задачи и пробелы из ответа участника или судьи. Негодная задача отбрасывается, но если
    не годится ни одна — ответ негодный; круг зависимостей — тоже."""
    raw = data.get("issues")
    if not isinstance(raw, list):
        raise BadAnswer("нет списка issues")
    gaps, refs = gaps_of(data.get("gaps"), context)
    valid, problems = [], []
    for n, item in enumerate(raw, 1):
        try:
            valid.append(candidate_of(item, context, gaps, refs, f"задача {n}"))
        except BadAnswer as exc:
            problems.append(str(exc))
    if problems and not valid:
        raise BadAnswer(problems[0])
    issues = linked(valid)
    if cycle := cycle_of(issues):
        raise BadAnswer(f"зависимости по кругу: {' → '.join(cycle)}")
    return Answer(tuple(issues), tuple(gaps))


def linked(issues: list[Candidate]) -> list[Candidate]:
    """Номер, который ответ дал двум задачам, ни одной из них не номер: на него не сослаться.
    Зависимости — только на задачи ответа с номером, не на себя."""
    counts = Counter(issue.name for issue in issues)
    named = [issue if counts[issue.name] == 1 else replace(issue, name="") for issue in issues]
    known = {issue.name for issue in named if issue.name}
    return [replace(issue, depends_on=tuple(dict.fromkeys(
        name for name in issue.depends_on if name in known and name != issue.name)))
        for issue in named]


def cycle_of(issues: list[Candidate]) -> list[str]:
    """Круг зависимостей, если он есть: номера по кругу, первый — и в конце."""
    graph = {issue.name: issue.depends_on for issue in issues if issue.name}
    state: dict[str, int] = {}                       # 1 — на пути, 2 — проверен
    path: list[str] = []

    def visit(name: str) -> list[str]:
        state[name] = 1
        path.append(name)
        for after in graph.get(name, ()):
            if state.get(after) == 1:
                return [*path[path.index(after):], after]
            if after not in state and (found := visit(after)):
                return found
        path.pop()
        state[name] = 2
        return []

    for name in graph:
        if name not in state and (found := visit(name)):
            return found
    return []


def as_prompt(answer: Answer) -> dict:
    """Задачи для судьи — в той же форме, в какой их просили у участников, и пробелы с их
    номерами: на них ссылается blocked_by. Задача без номера получает номер, которого нет ни у
    одной другой: иначе судья не отличил бы её от тёзки."""
    taken = {issue.name for issue in answer.issues if issue.name}
    free = (f"I{n}" for n in itertools.count(1) if f"I{n}" not in taken)
    return {
        "issues": [{
            "id": issue.name or next(free), "title": issue.title, "user_story": issue.user_story,
            "main_entry_points": list(issue.entry_points), "current_state": issue.current_state,
            "scope": list(issue.scope), "outcome_ids": list(issue.outcome_ids),
            "adr_ids": list(issue.adr_ids),
            "constraint_ids": [f"F{i}" for i in issue.constraint_ids],
            "risk_ids": [f"F{i}" for i in issue.risk_ids],
            "depends_on": list(issue.depends_on), "blocked_by": list(issue.blocked_by),
        } for issue in answer.issues],
        "gaps": [{"id": f"G{n}", "question": gap.question, "reason": gap.reason,
                  "outcome_ids": list(gap.outcome_ids)} for n, gap in enumerate(answer.gaps, 1)],
    }


def same_issues(answer: Answer) -> str:
    """Набор задач для сравнения: порядок задач, их пунктов и пробелов модели не держат —
    одинаковые наборы в разном порядке — один набор. Номера задач в ответах свои, поэтому
    зависимость сравнивается не номером, а тем, на какую задачу он указывает."""
    data = as_prompt(answer)

    def content(issue: dict) -> str:
        own = {key: value for key, value in issue.items() if key not in ("id", "depends_on")}
        for key in ("main_entry_points", "scope"):
            own[key] = sorted(own[key])
        return json.dumps(own, ensure_ascii=False, sort_keys=True)

    contents = {issue["id"]: content(issue) for issue in data["issues"]}
    issues = sorted(json.dumps({"issue": contents[issue["id"]],
                                "after": sorted(contents[name] for name in issue["depends_on"])},
                               ensure_ascii=False, sort_keys=True) for issue in data["issues"])
    gaps = sorted(json.dumps(gap, ensure_ascii=False, sort_keys=True) for gap in data["gaps"])
    return json.dumps({"issues": issues, "gaps": gaps}, ensure_ascii=False, sort_keys=True)
