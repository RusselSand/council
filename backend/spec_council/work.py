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

from collections.abc import Collection, Iterable, Mapping

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
from .pipeline import (
    choice_entry,
    decisions_key,
    outcome_print,
    project_prints,
    question_key,
    rests_on,
)


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


def carried_analyses(stream: Stream, choices: list[Choice],
                     anew: Collection[str] = ()) -> dict[str, QuestionAnalysis]:
    """Проверка того же выбора по тем же вопросам — нынешняя или из прежней работы: её не
    повторяют, пока выбор по вопросам, от которых она зависит, тот же (holds). anew — вопросы,
    которые человек просит перепроверить: их проверку не переносят."""
    keys = keys_of(stream.scope or [])
    analyzed = analyzed_of(stream.analysis)
    works = {work.key: work for work in stream.earlier}
    now = {choice.question_id: choice_entry(choice) for choice in choices}
    carried = {}
    for choice in choices:
        if choice.question_id in anew:
            continue
        entry = choice_entry(choice)
        found = analyzed.get(entry)
        work = works.get(keys.get(choice.question_id, ""))
        if found is None and work is not None and choice_entry(work.choice) == entry:
            found = work.analysis
        if found is not None and holds(found, now):
            carried[choice.question_id] = found
    return carried


def holds(found: QuestionAnalysis, now: Mapping[str, str]) -> bool:
    """Проверка держится, пока выбор по вопросам, на которые она опирается, тот же, что был при
    ней: противоречие с соседним вопросом могло уйти вместе с его прежним выбором. Опирается она
    на вопросы, от которых зависит, и на те, где судья велел что-то поправить (rests_on).
    Проверка, которая выбора не запомнила (её делали до того, как стали помнить), а на вопросы
    опирается, — уже не держится: что тогда было выбрано, не узнать."""
    return all(now.get(name) in found.context for name in rests_on(found))


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
    (тот же вопрос, вариант и обоснование): и те, что итог реализует, и те, на которые
    опирается. Номера решений — по новому отбору: ADR-n — n-й вопрос, и вопросы могли добавить
    или убрать. Прошлое решение проекта, на которое итог опирается, должно быть по-прежнему
    отобрано для потока, действовать и быть тем же, что видели при сборке: сняли отметку, оно
    уже не действует или его поправили в каталоге — итог собирают заново. released — итоги,
    которые человек велел пересобрать."""
    before = remembered(stream)["earlier_outcomes"]
    if not isinstance(before, OutcomeDiscovery):
        return []
    now = {decision.question_id: decision for decision in decisions}
    position = {question.id: n for n, question in enumerate(scope, 1)}

    def renumbered(name: str) -> str | None:
        """ADR-n прежней сборки — по новому отбору; решение уже не то — None."""
        n = int(name.split("-")[1])
        entry = before.decisions[n - 1] if 0 < n <= len(before.decisions) else ""
        question = entry.split(": ", 1)[0]
        decision = now.get(question)
        if (decision is None or decision.proposal is None
                or decisions_key([decision])[0] != entry or question not in position):
            return None
        return f"ADR-{position[question]}"

    def by_number(names: Iterable[str]) -> list[str]:
        return sorted(names, key=lambda name: int(name.split("-")[1]))

    chosen = active_decisions(stream)
    contents = project_prints(stream.project_decisions or [])
    kept = []
    for outcome in before.outcomes:
        if outcome.id in set(released) or not outcome_ready(outcome):
            continue
        if any(name not in chosen or before.projects.get(name) != contents.get(name)
               for name in outcome.project_decision_ids):
            continue
        names = {name: renumbered(name)
                 for name in (*outcome.adr_ids, *outcome.relies_on_adr_ids)}
        # Итог без единого решения ни на чём не стоит; опираться — тоже стоять, и на решение
        # проекта тоже: такой итог закрепляется, если не поменялось ни одно из его решений.
        if not (names or outcome.project_decision_ids) or None in names.values():
            continue
        kept.append(outcome.model_copy(update={
            "adr_ids": by_number(names[name] for name in outcome.adr_ids),
            "relies_on_adr_ids": by_number(names[name] for name in outcome.relies_on_adr_ids),
            "adr_notes": {names[name]: text for name, text in outcome.adr_notes.items()
                          if names.get(name)}}))
    return kept


def active_decisions(stream: Stream) -> set[str]:
    """Прошлые решения проекта, на которые итог может опираться: отобранные для потока и
    действующие."""
    return {decision.adr_id for decision in stream.project_decisions or []
            if decision.status == "active"}


def carried_issues(stream: Stream, outcomes: list[Outcome]) -> list[Issue]:
    """Задачи прежней нарезки, которые остаются: каждый их итог — тот же, что тогда нарезали, и
    по-прежнему готов (решение не пропало — иначе задачу бы заблокировали), задача ничем не
    заблокирована, каждое её решение — то же (номер ADR — к новому отбору), и всё, от чего она
    зависит, тоже остаётся. Они уже в разработке — их не нарезают заново."""
    before = remembered(stream)["earlier_issues"]
    if not isinstance(before, IssueDiscovery):
        return []
    projects = project_prints(stream.project_decisions or [])
    prints = {outcome.id: outcome_print(outcome, stream.scope or [], projects)
              for outcome in outcomes if outcome_ready(outcome)}
    # Решения итога — и реализуемые, и те, на которые он опирается: задача стоит на всех (их
    # наследует при нарезке). Отпечаток итога номеров не держит — они сдвигаются с отбором, —
    # поэтому какие именно это решения, сверяется здесь, по номерам к нынешнему отбору.
    rests = {outcome.id: {*outcome.adr_ids, *outcome.relies_on_adr_ids} for outcome in outcomes}
    fit = {issue.id: renumbered for issue in before.issues
           if not issue.blocked_by and issue.outcome_ids
           and all(name in prints and before.cut.get(name) == prints[name]
                   for name in issue.outcome_ids)
           and (renumbered := with_new_adrs(issue, before.decisions, stream)) is not None
           and all(rests[name] <= set(renumbered.adr_ids) for name in issue.outcome_ids)}
    while dropped := [name for name, issue in fit.items()
                      if any(other not in fit for other in issue.depends_on)]:
        for name in dropped:
            del fit[name]
    return [fit[issue.id] for issue in before.issues if issue.id in fit]


def with_new_adrs(issue: Issue, decided: list[str], stream: Stream) -> Issue | None:
    """Задача с номерами ADR по нынешнему отбору: ADR-n прежней нарезки — n-е из решений, к
    которым резали (decided). Решение уже не то — задача не та: None."""
    position = {question.id: n for n, question in enumerate(stream.scope or [], 1)}
    now = {decision.question_id: decision for decision in stream.decisions or []}
    adrs = []
    for name in issue.adr_ids:
        n = int(name.split("-")[1])
        entry = decided[n - 1] if 0 < n <= len(decided) else ""
        question = entry.split(": ", 1)[0]
        decision = now.get(question)
        if (decision is None or decision.proposal is None or question not in position
                or decisions_key([decision])[0] != entry):
            return None
        adrs.append(f"ADR-{position[question]}")
    return issue.model_copy(update={
        "adr_ids": sorted(adrs, key=lambda name: int(name.split("-")[1]))})


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


def known_decisions(stream: Stream) -> list[Decision]:
    """Решения, какие известны сейчас: зафиксированные, а пока их нет (после правки отбора или
    выбора) — прежние по тем же вопросам к тому же выбору; выбор ещё не утверждали — к прежнему."""
    if stream.decisions is not None:
        return stream.decisions
    works = {work.key: work for work in stream.earlier}
    choices = {choice.question_id: choice for choice in stream.choices or []}
    known = []
    for question in stream.scope or []:
        work = works.get(question_key(question))
        if work is None or work.decision is None:
            continue
        choice = choices.get(question.id)
        if stream.choices is not None and (
                choice is None or choice_entry(choice) != choice_entry(work.choice)):
            continue
        known.append(work.decision)
    return known


def saved_outcomes_of(stream: Stream) -> list[Outcome]:
    """Прежние итоги, которые останутся, если решения не поменяются: те, что закрепятся при новой
    сборке. Пока поток до неё не дошёл (итогов нет) — их видно на шаге «Итоги»; дошёл — шаг
    показывает свою сборку, а в ней они с самого начала."""
    if stream.outcomes is not None or stream.scope is None:
        return []
    return kept_outcomes(stream, stream.scope, known_decisions(stream))


def saved_issues_of(stream: Stream) -> list[Issue]:
    """Прежние задачи, которые перенесутся, пока поток до нарезки не дошёл: к итогам, какие есть
    (собранные, в идущей сборке — закреплённые, а пока сборки нет — те, что закрепятся), и
    решениям, какие известны."""
    if stream.issues is not None or stream.scope is None:
        return []
    if stream.outcomes is None:
        outcomes = saved_outcomes_of(stream)
    elif stream.outcomes.state == "done":
        # Итог, который задевают новые решения, ещё могут пересобрать: его задачи не сохранены,
        # пока человек не оставил его как есть.
        touched = {touch.outcome_id for touch in stream.outcomes.touched}
        outcomes = [o for o in stream.outcomes.outcomes if o.id not in touched]
    else:
        outcomes = [o for o in stream.outcomes.outcomes if o.id in stream.outcomes.kept]
    return carried_issues(stream.model_copy(update={"decisions": known_decisions(stream)}),
                          outcomes)


def with_kept(stream: Stream) -> Stream:
    """Поток, сохранённый, пока сборка и нарезка начинались пустыми (у сборки — только номера
    закреплённых): незаконченная получает закреплённые итоги и перенесённые задачи, как теперь
    начинается любая, — иначе их не видно, пока её не запустят снова. Менять нечего — тот же."""
    changes: dict[str, OutcomeDiscovery | IssueDiscovery] = {}
    run = stream.outcomes
    if (run is not None and run.state != "done" and run.kept and not run.outcomes
            and stream.scope is not None and stream.decisions is not None):
        changes["outcomes"] = run.model_copy(update={"outcomes": [
            outcome for outcome in kept_outcomes(stream, stream.scope, stream.decisions)
            if outcome.id in run.kept]})
    cut = stream.issues
    if (cut is not None and cut.state != "done" and not cut.issues
            and stream.outcomes is not None and stream.outcomes.state == "done"):
        carried = carried_issues(stream, stream.outcomes.outcomes)
        if carried:
            changes["issues"] = cut.model_copy(update={
                "issues": carried, "kept": [issue.id for issue in carried]})
    return stream.model_copy(update=changes) if changes else stream


def cutting_plan(stream: Stream) -> tuple[list[Issue], list[str]]:
    """Что перенести и что нарезать: задачи прежней нарезки тех же итогов и итоги, которые
    ими не покрыты."""
    outcomes = stream.outcomes.outcomes if stream.outcomes else []
    carried = carried_issues(stream, outcomes)
    return carried, uncut(stream, outcomes, carried)
