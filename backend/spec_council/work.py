"""Работа по вопросам, которая переживает правку отбора и выбора.

Правило одно: всё, что сделано по вопросу, живёт, пока сам вопрос тот же — тот же номер и та же
формулировка, — а проверка выбора и решение — пока тот же и выбор по нему. Добавили к отбору
вопросы — варианты ищут только к ним, проверяют только их выбор, человек решает только их;
остальное переносится. Иначе каждый добавленный вопрос стоил бы всей цепочки заново: поиска
вариантов по всем вопросам, проверки всего выбора и всех решений с обоснованиями.

Соседи у перенесённого вопроса поменялись, а его варианты и проверку искали без них: это
осознанно — новый вопрос, в свою очередь, видит все остальные.
"""

from collections.abc import Iterable

from .models import (
    Choice,
    DecisionAnalysis,
    OpenQuestion,
    ProposalDiscovery,
    QuestionAnalysis,
    QuestionOptions,
    QuestionWork,
    Stream,
)
from .pipeline import choice_entry, question_key


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
