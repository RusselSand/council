"""План задач на весь совет: что видят модели и как проверяется их ответ.

План строят, когда во всех потоках итоги утверждены и выгружены в заметки: тогда у каждого
итога и решения есть номер заметки (OUT-…, ADR-…), и модели называют их им — те же номера ложатся
в файлы задач, и ссылки в тексте задачи сразу верные. Итог, что в заметки не лёг (у него нет
решений своей идеи), в план не входит — это видно.

Ответ модели проверяет код: у задачи ровно один итог — из плана; решения, ограничения и риски —
только из данных; зависимости — только на задачи того же плана, без себя и без кругов (круг —
негодный ответ). Номера задач код раздаёт заново по порядку плана: I1, I2…
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .models import Council, Issue, LabeledFragment, Outcome, Stream
from .slicing import BadAnswer

TEXT_MAX = 4000
ITEMS_MAX = 20


@dataclass(frozen=True)
class Context:
    """На что задача может сослаться: итоги плана, решения, ограничения и риски итогов."""

    outcomes: frozenset[str]
    adrs: frozenset[str]
    constraints: frozenset[int]
    risks: frozenset[int]


@dataclass(frozen=True)
class Inputs:
    """Что видят модели (values — подстановки промптов, кроме кода и макета), на что можно
    сослаться, итоги плана по порядку, что в план не вошло и к чему он (basis)."""

    values: dict[str, str]
    context: Context
    outcomes: list[str]
    skipped: list[str]
    basis: dict[str, str]


def as_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def basis_of(council: Council) -> dict[str, str]:
    """К чему план: у каждого потока — его утверждённые итоги и выгрузка."""
    return {stream.group: f"{stream.outcomes.run if stream.outcomes else ''}:"
                          f"{stream.notes.run if stream.notes else ''}"
            for stream in council.streams or []}


def not_ready(council: Council, notes: str | None) -> list[str]:
    """Почему план строить рано: какой поток не утвердил итоги или не выгружен к ним в нынешний
    каталог заметок — или выгружен, когда совет ещё не помнил номера заметок (`refs`): тогда
    модели не узнали бы, как зовут его итоги. Пусто — можно."""
    if not council.streams:
        return ["Группы ещё не подтверждены"]
    problems = []
    for stream in council.streams:
        outcomes = stream.outcomes
        if outcomes is None or not outcomes.approved:
            problems.append(f"Поток {stream.group}: итоги не утверждены")
        elif (stream.notes is None or notes is None or stream.notes.root != notes
              or stream.notes.outcomes != outcomes.run):
            problems.append(f"Поток {stream.group}: не выгружен в заметки к утверждённым итогам")
        elif not stream.notes.refs:
            problems.append(f"Поток {stream.group}: выгружен до того, как совет стал помнить "
                            "номера заметок, — выгрузите его заново")
    return problems


def ideas_text(council: Council) -> str:
    titles = {group.id: group.title for group in council.structure.groups}
    return "\n".join(f"{stream.group}. {titles.get(stream.group, '')}: {stream.idea.text}"
                     for stream in council.streams or [] if stream.idea is not None)


def inputs_of(council: Council) -> Inputs:
    """Итоги всех потоков с номерами заметок, их решения, решения проекта, на которые они
    опираются, ограничения и риски."""
    fragments = {f.id: f for f in council.slicing.fragments} if council.slicing else {}
    outcomes: list[dict] = []
    decisions: dict[str, dict] = {}
    constraints: set[int] = set()
    risks: set[int] = set()
    skipped: list[str] = []
    for stream in council.streams or []:
        refs = stream.notes.refs if stream.notes else {}
        written = {note.id: note.written for note in stream.notes.notes} if stream.notes else {}
        for outcome in stream.outcomes.outcomes if stream.outcomes else []:
            note = refs.get(outcome.id)
            if note is None:
                skipped.append(f"Поток {stream.group}: {outcome.id} «{outcome.title}» не лёг в "
                               "заметки — в план не входит")
                continue
            outcomes.append(outcome_entry(outcome, note, stream.group, refs))
            constraints |= set(outcome.constraint_ids)
            risks |= set(outcome.risk_ids)
            for name in (*outcome.adr_ids, *outcome.relies_on_adr_ids):
                if name in refs:
                    decisions[refs[name]] = adr_entry(stream, name, refs[name], written)
            projects = {d.adr_id: d for d in stream.project_decisions or []}
            for adr_id in outcome.project_decision_ids:
                if adr_id in projects:
                    found = projects[adr_id]
                    decisions[adr_id] = {"id": adr_id, "project": True, "idea": found.idea,
                                         "question": found.question, "decision": found.decision,
                                         "status": found.status,
                                         "superseded_by": found.superseded_by}
    values = {"ideas": ideas_text(council), "outcomes": as_json(outcomes),
              "decisions": as_json(list(decisions.values())),
              "constraints_and_risks": as_json(limits_prompt(fragments, constraints | risks))}
    context = Context(frozenset(o["id"] for o in outcomes), frozenset(decisions),
                      frozenset(constraints), frozenset(risks))
    return Inputs(values, context, [o["id"] for o in outcomes], skipped, basis_of(council))


def outcome_entry(outcome: Outcome, note: str, group: str, refs: Mapping[str, str]) -> dict:
    """Итог, как его видят модели: номер заметки, поток, что меняется и чем проверить, какие
    решения он реализует и на какие опирается — номерами заметок."""
    return {"id": note, "group": group, "title": outcome.title, "behavior": outcome.behavior,
            "acceptance_criteria": outcome.acceptance_criteria,
            "implements": [refs[name] for name in outcome.adr_ids if name in refs],
            "follows": {refs[name]: text for name, text in outcome.adr_notes.items()
                        if name in refs},
            "relies_on": [refs[name] for name in outcome.relies_on_adr_ids if name in refs],
            "project_decisions": outcome.project_decision_ids,
            "constraint_ids": outcome.constraint_ids, "risk_ids": outcome.risk_ids}


def adr_entry(stream: Stream, name: str, note: str, written: Mapping[str, str]) -> dict:
    """Решение потока: номер заметки, вопрос и текст, как он лёг в заметку («решение, потому
    что обоснование»)."""
    n = int(name.split("-")[1])
    scope = stream.scope or []
    question = scope[n - 1] if 0 < n <= len(scope) else None
    return {"id": note, "question": (question.note or question.text) if question else "",
            "decision": written.get(note, "")}


def limits_prompt(fragments: Mapping[int, LabeledFragment], ids: Iterable[int]) -> list[dict]:
    return [{"id": i, "type": fragments[i].label, "text": fragments[i].text}
            for i in sorted(ids) if i in fragments]


def text_of(value: object, what: str, required: bool = True) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if required and not text:
        raise BadAnswer(f"у задачи нет {what}")
    if len(text) > TEXT_MAX:
        raise BadAnswer(f"{what} задачи длиннее {TEXT_MAX} знаков")
    return text


def texts_of(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()][:ITEMS_MAX]


def relabeled(text: str, names: Mapping[str, str]) -> str:
    """Номера задач в тексте — новыми (names: прежний → новый), за один проход: I1 ↔ I2 не
    путаются."""
    if not names:
        return text
    pattern = re.compile(r"(?<![\w-])(" + "|".join(
        re.escape(name) for name in sorted(names, key=len, reverse=True)) + r")(?![\w-])")
    return pattern.sub(lambda found: names[found.group(1)], text)


def plan_of(data: dict, context: Context) -> list[Issue]:
    """План из ответа модели: задачи по порядку, с номерами I1, I2… — и в тексте задач тоже.
    Задача, чей итог не из плана, отбрасывается — как и ссылки, которых нет в данных."""
    items = data.get("issues")
    if not isinstance(items, list):
        raise BadAnswer("нет списка issues")
    kept: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or item.get("outcome_id") not in context.outcomes:
            continue
        name = item.get("id") if isinstance(item.get("id"), str) else ""
        if name in seen:
            raise BadAnswer(f"номер {name} у двух задач")
        seen.add(name)
        kept.append((name, item))
    renamed = {name: f"I{n}" for n, (name, _) in enumerate(kept, 1) if name}
    issues = []
    for n, (_, item) in enumerate(kept, 1):
        issue_id = f"I{n}"
        after = [renamed[d] for d in texts_of(item.get("depends_on"))
                 if d in renamed and renamed[d] != issue_id]
        def text(value: str) -> str:
            return relabeled(value, renamed)

        issues.append(Issue(
            id=issue_id, title=text(text_of(item.get("title"), "названия")),
            user_story=text(text_of(item.get("user_story"), "user story")),
            main_entry_points=texts_of(item.get("main_entry_points")),
            current_state=text(text_of(item.get("current_state"), "нынешнего состояния", False)),
            scope=[text(line) for line in texts_of(item.get("scope"))],
            outcome_id=item["outcome_id"],
            adr_ids=[a for a in texts_of(item.get("adr_ids")) if a in context.adrs],
            constraint_ids=ints_in(item.get("constraint_ids"), context.constraints),
            risk_ids=ints_in(item.get("risk_ids"), context.risks),
            depends_on=list(dict.fromkeys(after)),
            open_questions=[text(line) for line in texts_of(item.get("open_questions"))]))
    cycle = cycle_of(issues)
    if cycle:
        raise BadAnswer(f"зависимости по кругу: {' → '.join(cycle)}")
    return issues


def ints_in(value: object, allowed: frozenset[int]) -> list[int]:
    if not isinstance(value, list):
        return []
    found = [item for item in value if isinstance(item, int) and not isinstance(item, bool)]
    return sorted({item for item in found if item in allowed})


def cycle_of(issues: Sequence[Issue]) -> list[str]:
    """Круг в зависимостях плана, если он есть: номера по кругу. Нет — пусто."""
    after = {issue.id: issue.depends_on for issue in issues}
    state: dict[str, str] = {}

    def visit(name: str, path: list[str]) -> list[str]:
        state[name] = "open"
        for other in after.get(name, []):
            if state.get(other) == "open":
                return [*path[path.index(other):], other] if other in path else [name, other]
            if other not in state:
                found = visit(other, [*path, other])
                if found:
                    return found
        state[name] = "done"
        return []

    for issue in issues:
        if issue.id not in state:
            found = visit(issue.id, [issue.id])
            if found:
                return found
    return []


def same_plan(plans: Sequence[Sequence[Issue]]) -> bool:
    """Планы совпали — судья не нужен."""
    shapes = {json.dumps([issue.model_dump() for issue in plan], ensure_ascii=False,
                         sort_keys=True) for plan in plans}
    return len(shapes) == 1


def plan_prompt(plan: Sequence[Issue]) -> list[dict]:
    """План участника, как его видит судья."""
    return [issue.model_dump() for issue in plan]
