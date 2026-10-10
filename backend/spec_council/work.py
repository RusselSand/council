"""Работа по вопросам, которая переживает правку отбора и выбора.

Правило одно: всё, что сделано по вопросу, живёт, пока сам вопрос тот же — тот же номер и та же
формулировка, — а проверка выбора и решение — пока тот же и выбор по нему. Добавили к отбору
вопросы — варианты ищут только к ним, проверяют только их выбор, человек решает только их;
остальное переносится. Иначе каждый добавленный вопрос стоил бы всей цепочки заново: поиска
вариантов по всем вопросам, проверки всего выбора и всех решений с обоснованиями.

Соседи у перенесённого вопроса поменялись, а его варианты и проверку искали без них: это
осознанно — новый вопрос, в свою очередь, видит все остальные.

То же с итогами и задачами: итог, который был готов и чьи решения те же, закрепляется — его не
пересобирают, а модели видят его данностью; задачи такого итога (тот же итог — те же задачи,
ничто их не держит) переносятся, а не нарезаются заново: они уже в разработке.
"""

from collections.abc import Iterable

from .models import (
    Choice,
    Decision,
    DecisionAnalysis,
    Issue,
    IssueDiscovery,
    OpenQuestion,
    Outcome,
    OutcomeDiscovery,
    ProposalDiscovery,
    QuestionAnalysis,
    QuestionOptions,
    QuestionWork,
    Stream,
)
from .pipeline import choice_entry, decisions_key, outcome_print, question_key


def keys_of(scope: Iterable[OpenQuestion]) -> dict[str, str]:
    """Вопросы отбора: номер — как его узнают после правки (номер и формулировка)."""
    return {question.id: question_key(question) for question in scope}


def carried_options(search: ProposalDiscovery | None,
                    scope: list[OpenQuestion]) -> dict[str, QuestionOptions]:
    """Варианты, найденные раньше к тем же вопросам, что и в отборе: их не ищут заново."""
    if search is None:
        return {}
    known, keys = set(search.scope), keys_of(scope)
    return {options.question_id: options for options in search.options
            if keys.get(options.question_id) in known}


def analyzed_of(analysis: DecisionAnalysis | None) -> dict[str, QuestionAnalysis]:
    """Проверка по каждому выбору, который она проверила: «Q1: P2» — её анализ."""
    if analysis is None:
        return {}
    entries = {entry.split(": ", 1)[0]: entry for entry in analysis.choices}
    return {entries[found.question_id]: found for found in analysis.analyses
            if found.question_id in entries}


def kept_work(stream: Stream) -> list[QuestionWork]:
    """Работа по каждому вопросу — нынешняя, а где её уже сняли (после правки отбора выбор ещё
    не утвердили) — прежняя. Её запоминают перед тем, как правка отбора или выбора снимет
    выбор, проверку и решения."""
    works = {work.key: work for work in stream.earlier}
    if stream.scope is None or stream.choices is None:
        return list(works.values())
    keys = keys_of(stream.scope)
    analyzed = analyzed_of(stream.analysis)
    decisions = {decision.question_id: decision for decision in stream.decisions or []}
    for choice in stream.choices:
        key = keys.get(choice.question_id)
        if key is None:
            continue
        before = works.get(key)
        same = before is not None and choice_entry(before.choice) == choice_entry(choice)
        works[key] = QuestionWork(
            key=key, choice=choice,
            analysis=analyzed.get(choice_entry(choice)) or (before.analysis if same else None),
            decision=decisions.get(choice.question_id) or (before.decision if same else None))
    return list(works.values())


def carried_analyses(stream: Stream, choices: list[Choice]) -> dict[str, QuestionAnalysis]:
    """Проверка того же выбора по тем же вопросам — нынешняя или из прежней работы: её не
    повторяют."""
    keys = keys_of(stream.scope or [])
    analyzed = analyzed_of(stream.analysis)
    works = {work.key: work for work in stream.earlier}
    carried = {}
    for choice in choices:
        entry = choice_entry(choice)
        found = analyzed.get(entry)
        work = works.get(keys.get(choice.question_id, ""))
        if found is None and work is not None and choice_entry(work.choice) == entry:
            found = work.analysis
        if found is not None:
            carried[choice.question_id] = found
    return carried


def earlier_choices(stream: Stream) -> dict[str, Choice]:
    """Прежний выбор по каждому вопросу отбора: утверждённый — или из прежней работы, если
    после правки отбора выбор ещё не утверждали."""
    if stream.choices is not None:
        return {choice.question_id: choice for choice in stream.choices}
    works = {work.key: work for work in stream.earlier}
    return {question.id: works[key].choice
            for question in stream.scope or [] if (key := question_key(question)) in works}


def last_used(stream: Stream) -> int:
    """Самый большой номер варианта, какой поток уже давал: найденные советом (и к вопросам,
    которых в отборе больше нет), свои варианты человека, проверки и решения — и в прежней
    работе тоже. Новые номера — только дальше: вопрос, вернувшийся в отбор, не должен узнать
    свой прежний выбор в чужом варианте под тем же номером."""
    ids = [proposal.id for options in (stream.proposals.options if stream.proposals else [])
           for proposal in options.proposals]
    # Поиск помнит, с какого номера нумеровал: варианты убранных вопросов ушли, их номера — нет.
    ids.append(f"P{stream.proposals.first - 1}" if stream.proposals else "")
    for choice in [*(stream.choices or []), *(work.choice for work in stream.earlier)]:
        ids.append(choice.proposal or "")
    for work in stream.earlier:
        ids += [work.analysis.proposal if work.analysis else None,
                work.decision.proposal if work.decision else None]
    ids += [decision.proposal for decision in stream.decisions or []]
    return max((int(i[1:]) for i in ids if i and i.startswith("P") and i[1:].isdigit()),
               default=0)


def outcome_ready(outcome: Outcome) -> bool:
    """Итог готов к разработке: его не держат ни открытые вопросы, ни пробелы, и есть чем
    проверить, что он сделан."""
    return not outcome.blocked_by and not outcome.gaps and bool(outcome.acceptance_criteria)


def remembered(stream: Stream) -> dict[str, OutcomeDiscovery | IssueDiscovery | None]:
    """Что запомнить, когда правка снимает итоги и задачи: последние собранные и нарезанные — из
    них закрепят готовое, а не соберут и не нарежут заново."""
    outcomes = stream.outcomes if stream.outcomes and stream.outcomes.state == "done" else None
    issues = stream.issues if stream.issues and stream.issues.state == "done" else None
    return {"earlier_outcomes": outcomes or stream.earlier_outcomes,
            "earlier_issues": issues or stream.earlier_issues}


def kept_outcomes(stream: Stream, scope: list[OpenQuestion], decisions: list[Decision],
                  released: Iterable[str] = ()) -> list[Outcome]:
    """Итоги, которые закрепляются при новой сборке: были готовы, и каждое их решение — то же
    (тот же вопрос, вариант и обоснование). Номера решений — по новому отбору: ADR-n — n-й
    вопрос, и вопросы могли добавить или убрать. released — итоги, которые человек велел
    пересобрать."""
    before = remembered(stream)["earlier_outcomes"]
    if not isinstance(before, OutcomeDiscovery):
        return []
    now = {decision.question_id: decision for decision in decisions}
    position = {question.id: n for n, question in enumerate(scope, 1)}
    kept = []
    for outcome in before.outcomes:
        if outcome.id in set(released) or not outcome_ready(outcome):
            continue
        adrs = []
        for name in outcome.adr_ids:
            n = int(name.split("-")[1])
            entry = before.decisions[n - 1] if 0 < n <= len(before.decisions) else ""
            question = entry.split(": ", 1)[0]
            decision = now.get(question)
            if (decision is None or decision.proposal is None
                    or decisions_key([decision])[0] != entry or question not in position):
                break
            adrs.append(f"ADR-{position[question]}")
        else:
            if adrs:
                kept.append(outcome.model_copy(update={
                    "adr_ids": sorted(adrs, key=lambda name: int(name.split("-")[1]))}))
    return kept


def carried_issues(stream: Stream, outcomes: list[Outcome]) -> list[Issue]:
    """Задачи прежней нарезки, которые остаются: каждый их итог — тот же, что тогда нарезали,
    задача ничем не заблокирована, и всё, от чего она зависит, тоже остаётся. Они уже в
    разработке — их не нарезают заново."""
    before = remembered(stream)["earlier_issues"]
    if not isinstance(before, IssueDiscovery):
        return []
    prints = {outcome.id: outcome_print(outcome) for outcome in outcomes}
    fit = {issue.id: issue for issue in before.issues
           if not issue.blocked_by and issue.outcome_ids
           and all(name in prints and before.cut.get(name) == prints[name]
                   for name in issue.outcome_ids)}
    while dropped := [name for name, issue in fit.items()
                      if any(other not in fit for other in issue.depends_on)]:
        for name in dropped:
            del fit[name]
    return [issue for issue in before.issues if issue.id in fit]


def uncut(stream: Stream, outcomes: list[Outcome], carried: list[Issue]) -> list[str]:
    """Итоги, которые ещё надо нарезать: все, кроме целиком покрытых перенесёнными задачами —
    у такого итога есть перенесённая задача, и ни одной его прежней задачи не потеряли."""
    before = remembered(stream)["earlier_issues"]
    previous = before.issues if isinstance(before, IssueDiscovery) else []
    kept = {issue.id for issue in carried}
    covered = {name for issue in carried for name in issue.outcome_ids}
    lost = {name for issue in previous if issue.id not in kept for name in issue.outcome_ids}
    return [outcome.id for outcome in outcomes
            if outcome.id not in covered or outcome.id in lost]


def cutting_plan(stream: Stream) -> tuple[list[Issue], list[str]]:
    """Что перенести и что нарезать: задачи прежней нарезки тех же итогов и итоги, которые
    ими не покрыты."""
    outcomes = stream.outcomes.outcomes if stream.outcomes else []
    carried = carried_issues(stream, outcomes)
    return carried, uncut(stream, outcomes, carried)
