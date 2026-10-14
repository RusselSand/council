"""Задачи потока: разбор ответов участников и судьи, проверка ссылок. Без ввода-вывода.

Задача (issue) реализует часть ровно одного утверждённого итога: итоги режут по одному, и
задачи их не пересобирают. Она стоит на решениях своего итога и соблюдает его ограничения.
Ссылки вторичны: чужой номер просто отбрасывается, а задача остаётся. Но задача, которая
называет не свой итог или два итога, отбрасывается. Зависимости в ответе — только на задачи
того же ответа, без самой себя и без кругов: круг — негодный ответ. Зависимости между задачами
разных итогов ставит потом судья, видя все задачи разом (dependencies_of). Номер, который ответ
дал двум задачам, — ссылка на неизвестно какую из них: такие ссылки не берём. Задачу блокирует
пробел того же ответа (G-n) или открытый вопрос потока. Пробел, совпавший с открытым вопросом
отбора, — блокировка им, с решённым — уже ответ.
Список задач может быть и пустым: всё уже реализовано или заблокировано.
"""

import itertools
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
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
    # Что даёт задаче её итог, по его номеру.
    parents: Mapping[str, Parent] = field(default_factory=dict)
    # Перенесённые задачи прежней нарезки: новая может от них зависеть, а их номера — не её.
    fixed: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Parent:
    """Что задача берёт у своего итога: на чём он стоит (решения, ограничения, риски) и что его
    держит (открытые вопросы и пробелы — вопрос и почему)."""

    adr_ids: tuple[str, ...] = ()
    constraint_ids: tuple[int, ...] = ()
    risk_ids: tuple[int, ...] = ()
    blocked_by: tuple[str, ...] = ()
    gaps: tuple[tuple[str, str], ...] = ()


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
    texts = (reason_of(item) for item in as_list(value))
    return tuple(dict.fromkeys(text for text in texts if text and len(text) <= ITEM_MAX))


def outcomes_in(value: object, allowed: frozenset[str]) -> tuple[str, ...]:
    found = (OUTCOME_ID.fullmatch(item.strip()) for item in as_list(value)
             if isinstance(item, str))
    names = {f"O{int(match.group(1))}" for match in found if match}
    return tuple(sorted(names & allowed, key=lambda name: int(name[1:])))


def about(value: object, context: Context) -> tuple[str, ...]:
    """Про какие итоги пробел: названные моделью, а если не назвала и итог в ходе один — про
    него."""
    found = outcomes_in(value, context.outcomes)
    if not found and len(context.outcomes) == 1:
        return tuple(context.outcomes)
    return found


def name_of(value: object) -> str:
    found = ISSUE_ID.fullmatch(value.strip()) if isinstance(value, str) else None
    return f"I{int(found.group(1))}" if found else ""


def gaps_of(value: object, context: Context
            ) -> tuple[list[Gap], dict[int, str], dict[str, set[str]]]:
    """Пробелы ответа и куда ведёт ссылка на n-й из них: «G<k>» — на k-й оставшийся, «Q…» — на
    открытый вопрос отбора, с которым он совпал. Пробел, совпавший с решённым вопросом, — уже
    ответ, а пустой или длиннее вопроса отбор не примет: такие отбрасываются. Тот же вопрос
    дважды — один пробел, про итоги обоих. Пробел, совпавший с открытым вопросом, — этот
    вопрос, и итоги, что пробел назвал, — его: он держит их задачи (третье в ответе)."""
    items = value if isinstance(value, list) else []
    kept: list[Gap] = []
    refs: dict[int, str] = {}
    asked: dict[str, set[str]] = {}
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
                asked.setdefault(known, set()).update(about(item.get("outcome_ids"), context))
            continue
        refs[n] = joined(kept, question, reason_of(item.get("reason")),
                         about(item.get("outcome_ids"), context))
    return kept, refs, asked


def joined(gaps: list[Gap], question: str, reason: str, outcome_ids: tuple[str, ...]) -> str:
    """Пробел в список: тот же вопрос (как его сравнивает same_question) — тот же пробел, про
    итоги обоих и с объяснениями обоих. Вернёт его номер, G-n."""
    for n, gap in enumerate(gaps, 1):
        if same_question(gap.question) == same_question(question):
            reasons = [text for text in dict.fromkeys((*gap.reason.split("; "), reason)) if text]
            gaps[n - 1] = replace(gap, reason="; ".join(reasons),
                                  outcome_ids=ordered({*gap.outcome_ids, *outcome_ids}))
            return f"G{n}"
    gaps.append(Gap(question, reason, ordered(set(outcome_ids))))
    return f"G{len(gaps)}"


def ordered(outcome_ids: set[str]) -> tuple[str, ...]:
    return tuple(sorted(outcome_ids, key=lambda name: int(name[1:])))


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
    # Итог режут по одному: задача — его, даже если модель его не назвала. Назвала чужой или
    # два — задача не того итога.
    named = [name for name in as_list(item.get("outcome_ids")) if isinstance(name, str)]
    outcome_ids = about(item.get("outcome_ids"), context)
    foreign = bool(named) and not outcomes_in(named, context.outcomes)
    if len(outcome_ids) != 1 or len(named) > 1 or foreign:
        raise BadAnswer(f"{what}: задача — ровно одного утверждённого итога")
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
    gaps, refs, asked = gaps_of(data.get("gaps"), context)
    # Пробелы итогов — сразу: задача другого итога может сослаться на такой текстом, а пересказ
    # своими словами модели запрещены — тот же пробел дважды.
    for outcome_id, parent in context.parents.items():
        for question, reason in parent.gaps:
            joined(gaps, question, reason, (outcome_id,))
    valid, problems = [], []
    for n, item in enumerate(raw, 1):
        try:
            valid.append(candidate_of(item, context, gaps, refs, f"задача {n}"))
        except BadAnswer as exc:
            problems.append(str(exc))
    if problems and not valid:
        raise BadAnswer(problems[0])
    issues = linked(valid, context.fixed)
    if cycle := cycle_of(issues):
        raise BadAnswer(f"зависимости по кругу: {' → '.join(cycle)}")
    gaps, issues = placed(gaps, issues)
    issues = after_blocked([inherited(issue, gaps, context, asked) for issue in issues])
    return Answer(tuple(issues), tuple(gaps))


def after_blocked(issues: list[Candidate]) -> list[Candidate]:
    """Что держит задачу, держит и задачи после неё: их не начать, пока она не сделана, — модель
    может этого не повторить. Зависимости без кругов (их отверг разбор)."""
    named = {issue.name: issue for issue in issues if issue.name}
    held: dict[str, frozenset[str]] = {}

    def of(name: str) -> frozenset[str]:
        if name not in named:
            return frozenset()        # перенесённую задачу ничто не держит — её бы не перенесли
        if name not in held:
            issue = named[name]
            held[name] = frozenset(issue.blocked_by).union(*map(of, issue.depends_on))
        return held[name]

    return [replace(issue, blocked_by=tuple(sorted(frozenset(issue.blocked_by).union(
        *map(of, issue.depends_on))))) for issue in issues]


def inherited(issue: Candidate, gaps: list[Gap], context: Context,
              asked: Mapping[str, set[str]]) -> Candidate:
    """Задача стоит на том же, на чём её итог, и её держит то же — модель может забыть это
    повторить, а задача без решения не «можно брать», и без решения и ограничений итога агент
    сделал бы ей наперекор. Решения, ограничения и риски итога — и у задачи; открытый вопрос
    итога — в её blocked_by, как и каждый пробел, названный для её итога, и открытый вопрос,
    названный пробелом для её итога. Критерии готовности итога в задачу не переходят: итог
    готов, когда готовы все его задачи. Здесь, при разборе, — чтобы ответы, разные лишь тем,
    повторили ли они это, сравнивались одинаковыми."""
    parents = [context.parents[name] for name in issue.outcome_ids if name in context.parents]
    adrs = {*issue.adr_ids, *(name for parent in parents for name in parent.adr_ids)}
    blocked = {*issue.blocked_by,
               *(name for parent in parents for name in parent.blocked_by
                 if name in context.open_questions),
               *(f"G{n}" for n, gap in enumerate(gaps, 1)
                 if set(gap.outcome_ids) & set(issue.outcome_ids)),
               *(name for name, outcome_ids in asked.items()
                 if outcome_ids & set(issue.outcome_ids))}
    return replace(
        issue,
        adr_ids=tuple(sorted(adrs, key=lambda name: int(name.split("-")[1]))),
        constraint_ids=tuple(sorted({*issue.constraint_ids,
                                     *(n for parent in parents for n in parent.constraint_ids)})),
        risk_ids=tuple(sorted({*issue.risk_ids,
                               *(n for parent in parents for n in parent.risk_ids)})),
        blocked_by=tuple(sorted(blocked)))


def placed(gaps: list[Gap], issues: list[Candidate]) -> tuple[list[Gap], list[Candidate]]:
    """Пробел — про итоги, которые он назвал, и про итоги задач, которые он держит: модель могла
    их не назвать. Пробел ни к одному утверждённому итогу ничего не держит — он отбрасывается,
    а номера оставшихся идут по порядку."""
    about = {f"G{n}": set(gap.outcome_ids) for n, gap in enumerate(gaps, 1)}
    for issue in issues:
        for name in issue.blocked_by:
            if name in about:
                about[name].update(issue.outcome_ids)
    kept: list[Gap] = []
    renamed: dict[str, str] = {}
    for n, gap in enumerate(gaps, 1):
        if about[f"G{n}"]:
            kept.append(replace(gap, outcome_ids=ordered(about[f"G{n}"])))
            renamed[f"G{n}"] = f"G{len(kept)}"
    return kept, [replace(issue, blocked_by=tuple(sorted(
        renamed.get(name, name) for name in issue.blocked_by
        if name in renamed or not GAP_ID.fullmatch(name)))) for issue in issues]


def linked(issues: list[Candidate], fixed: frozenset[str] = frozenset()) -> list[Candidate]:
    """Номер, который ответ дал двум задачам, ни одной из них не номер: на него не сослаться.
    Зависимости — только на задачи ответа с номером, не на себя, и на перенесённые задачи
    прежней нарезки (fixed): их номер новой задаче не достаётся — ссылка на него — на них."""
    counts = Counter(issue.name for issue in issues)
    named = [issue if counts[issue.name] == 1 and issue.name not in fixed
             else replace(issue, name="") for issue in issues]
    known = {issue.name for issue in named if issue.name} | set(fixed)
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


def as_prompt(answer: Answer, fixed: Iterable[str] = ()) -> dict:
    """Задачи для судьи — в той же форме, в какой их просили у участников, и пробелы с их
    номерами: на них ссылается blocked_by. Задача без номера получает номер, которого нет ни у
    одной другой, и ни у перенесённой (fixed): иначе судья не отличил бы её от тёзки."""
    taken = {issue.name for issue in answer.issues if issue.name} | set(fixed)
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
    одинаковые наборы в разном порядке — один набор. Номера задач и пробелов в ответах свои
    (у пробела — его место в списке), поэтому зависимость и блокировка пробелом сравниваются не
    номером, а тем, на что он указывает."""
    data = as_prompt(answer)
    gaps = {gap["id"]: json.dumps({key: value for key, value in gap.items() if key != "id"},
                                  ensure_ascii=False, sort_keys=True) for gap in data["gaps"]}

    def content(issue: dict) -> str:
        own = {key: value for key, value in issue.items() if key not in ("id", "depends_on")}
        for key in ("main_entry_points", "scope"):
            own[key] = sorted(own[key])
        own["blocked_by"] = sorted(gaps.get(name, name) for name in issue["blocked_by"])
        return json.dumps(own, ensure_ascii=False, sort_keys=True)

    contents = {issue["id"]: content(issue) for issue in data["issues"]}
    if len(set(contents.values())) < len(contents):
        # Задачи-двойники по содержанию: по содержаниям граф не восстановить (общая ли у них
        # предшественница — не видно), и набор равен лишь буквально такому же — иначе судья.
        return json.dumps({"exact": data}, ensure_ascii=False, sort_keys=True)
    # Содержания разные — граф и есть рёбра между ними: «эта задача — после этих». Перенесённой
    # задачи в ответе нет — она одна и та же для всех: по номеру.
    issues = sorted(json.dumps({"issue": contents[issue["id"]],
                                "after": sorted(contents.get(name, f"fixed {name}")
                                                for name in issue["depends_on"])},
                               ensure_ascii=False, sort_keys=True) for issue in data["issues"])
    return json.dumps({"issues": issues, "gaps": sorted(gaps.values())}, ensure_ascii=False,
                      sort_keys=True)


def combined(parts: Iterable[Answer], fixed: Iterable[str] = ()) -> Answer:
    """Нарезки итогов, каждого своим ходом, — в одну. Номера в ответах свои у каждого итога:
    задачи получают сквозные (их ссылки внутри итога — по ним же), перенесённые задачи (fixed)
    свои номера сохраняют. Тот же пробел у разных итогов — один пробел про итоги обоих."""
    taken = set(fixed)
    fresh = (f"I{n}" for n in itertools.count(1) if f"I{n}" not in taken)
    issues: list[Candidate] = []
    gaps: list[Gap] = []
    for part in parts:
        names = {issue.name: next(fresh) for issue in part.issues if issue.name}
        places = {f"G{n}": joined(gaps, gap.question, gap.reason, gap.outcome_ids)
                  for n, gap in enumerate(part.gaps, 1)}
        for issue in part.issues:
            issues.append(replace(
                issue, name=names.get(issue.name) or next(fresh),
                depends_on=tuple(names.get(name, name) for name in issue.depends_on),
                blocked_by=tuple(sorted(places.get(name, name) for name in issue.blocked_by))))
    return Answer(tuple(issues), tuple(gaps))


def dependencies_prompt(answer: Answer, carried: Iterable[Mapping]) -> list[dict]:
    """Все задачи для судьи зависимостей: перенесённые и новые, с их итогом и зависимостями."""
    return [*({"id": issue["id"], "outcome_ids": list(issue["outcome_ids"]),
               "title": issue["title"], "user_story": issue["user_story"],
               "scope": list(issue["scope"]), "depends_on": list(issue["depends_on"]),
               "fixed": True} for issue in carried),
            *({"id": issue.name, "outcome_ids": list(issue.outcome_ids), "title": issue.title,
               "user_story": issue.user_story, "main_entry_points": list(issue.entry_points),
               "current_state": issue.current_state, "scope": list(issue.scope),
               "depends_on": list(issue.depends_on), "fixed": False}
              for issue in answer.issues)]


def dependencies_of(data: dict, answer: Answer,
                    fixed: Mapping[str, Iterable[str]]) -> Answer:
    """Зависимости между задачами разных итогов от судьи: какая новая задача после каких. Задачи
    он не меняет. Ссылка — только с новой задачи на задачу другого итога, новую или перенесённую
    (fixed — номер перенесённой и её итоги); остальное отбрасывается: зависимости внутри итога
    уже поставила его нарезка, а перенесённые задачи уже в разработке. Круг — негодный ответ.
    Что держит задачу, держит и задачи после неё."""
    items = data.get("dependencies")
    if not isinstance(items, list):
        raise BadAnswer("нет списка dependencies")
    outcomes = {issue.name: set(issue.outcome_ids) for issue in answer.issues}
    outcomes |= {name: set(ids) for name, ids in fixed.items()}
    added: dict[str, list[str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = name_of(item.get("issue_id"))
        if name not in outcomes or name in fixed:
            continue
        for after in map(name_of, as_list(item.get("depends_on"))):
            if after in outcomes and after != name and not outcomes[after] & outcomes[name]:
                added.setdefault(name, []).append(after)
    issues = [replace(issue, depends_on=tuple(dict.fromkeys(
        [*issue.depends_on, *added.get(issue.name, [])]))) for issue in answer.issues]
    if cycle := cycle_of(issues):
        raise BadAnswer(f"зависимости по кругу: {' → '.join(cycle)}")
    return Answer(tuple(after_blocked(issues)), answer.gaps)
