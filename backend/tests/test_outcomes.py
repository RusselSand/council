"""Итоги: разбор ответов, ссылки только на своё, блокировка только открытыми вопросами."""

from dataclasses import replace

import pytest

from spec_council.outcomes import (
    Candidate,
    Context,
    Gap,
    Touch,
    as_prompt,
    assembly_of,
    outcome_list,
)
from spec_council.slicing import BadAnswer

CONTEXT = Context(adrs=frozenset({"ADR-1", "ADR-3"}), constraints=frozenset({4}),
                  risks=frozenset({5}), open_questions=frozenset({"Q2"}))


def outcome(title="Поиск по базе знаний", behavior="Человек находит статью через поиск.",
            **extra):
    return {"title": title, "behavior": behavior, "adr_ids": ["ADR-1"],
            "constraint_ids": ["F4"], "risk_ids": [],
            "acceptance_criteria": ["Запрос возвращает подходящие статьи."],
            "blocked_by": [], "gaps": [], **extra}


def test_an_outcome_is_read_with_its_links():
    [found] = outcome_list({"outcomes": [outcome(
        adr_ids=["adr-3", "ADR 1", "ADR-2"], risk_ids=["F5", "F4"], blocked_by=["q2", "Q1"],
        acceptance_criteria=["  Запрос  возвращает статьи. ", "", "Запрос возвращает статьи."],
        gaps=[{"question": "Кто обновляет индекс?", "reason": "без этого нет критерия"},
              {"question": " "}, "пробел"])]}, CONTEXT)
    assert found == Candidate(
        "Поиск по базе знаний", "Человек находит статью через поиск.", ("ADR-1", "ADR-3"),
        (4,), (5,), ("Запрос возвращает статьи.",), ("Q2",),
        (Gap("Кто обновляет индекс?", "без этого нет критерия"),))


def test_only_an_open_question_blocks():
    """Q1 решён — он не держит; Q9 в потоке нет."""
    [found] = outcome_list({"outcomes": [outcome(blocked_by=["Q1", "Q9"])]}, CONTEXT)
    assert found.blocked_by == ()


@pytest.mark.parametrize(("bad", "problem"), [
    (outcome(title=" "), "title: пусто"),
    (outcome(behavior="x" * 2001), "behavior: длиннее"),
    ("итог", "не объект"),
])
def test_a_bad_outcome_is_dropped_and_only_bad_ones_make_a_bad_answer(bad, problem):
    assert len(outcome_list({"outcomes": [bad, outcome()]}, CONTEXT)) == 1
    with pytest.raises(BadAnswer, match=problem):
        outcome_list({"outcomes": [bad]}, CONTEXT)


def test_no_outcomes_is_an_honest_answer_but_no_list_is_not():
    assert outcome_list({"outcomes": [], "coverage": {}}, CONTEXT) == []
    with pytest.raises(BadAnswer, match="outcomes"):
        outcome_list({"items": []}, CONTEXT)


def test_the_judge_sees_an_outcome_as_the_participants_were_asked_for_it():
    [found] = outcome_list({"outcomes": [outcome(blocked_by=["Q2"])]}, CONTEXT)
    assert as_prompt(found) == {
        "title": "Поиск по базе знаний", "behavior": "Человек находит статью через поиск.",
        "adr_ids": ["ADR-1"], "constraint_ids": ["F4"], "risk_ids": [],
        "acceptance_criteria": ["Запрос возвращает подходящие статьи."], "blocked_by": ["Q2"],
        "gaps": []}


def test_a_gap_longer_than_a_question_is_dropped():
    """Пробел человек добавляет в вопросы: длиннее вопроса — отбор его не примет."""
    [found] = outcome_list({"outcomes": [outcome(gaps=[{"question": "x" * 501, "reason": "длинно"},
                                                       {"question": "Кто смотрит отчёт?"}])]},
                           CONTEXT)
    assert found.gaps == (Gap("Кто смотрит отчёт?", ""),)


def test_a_gap_that_is_a_scope_question_is_not_a_gap():
    """Открытый вопрос отбора блокирует итог, решённый уже ответил: новым вопросом ни один не
    стать."""
    scoped = Context(adrs=CONTEXT.adrs, constraints=CONTEXT.constraints, risks=CONTEXT.risks,
                     open_questions=CONTEXT.open_questions,
                     questions={"где живёт база": "Q2", "как искать": "Q1"})
    [found] = outcome_list({"outcomes": [outcome(gaps=[
        {"question": "Где живёт  база?", "reason": "нет решения"}, {"question": "Как искать."},
        {"question": "Кто смотрит отчёт?"}])]}, scoped)
    assert (found.blocked_by, found.gaps) == (("Q2",), (Gap("Кто смотрит отчёт?", ""),))


def test_a_touch_names_a_kept_outcome_and_only_decisions_new_to_it():
    context = replace(CONTEXT, kept={"O1": frozenset({"ADR-1"})})
    touches = assembly_of({"outcomes": [], "touches": [
        {"outcome_id": "O1", "adr_ids": ["ADR-1", "ADR-3"], "reason": "меняет поиск"},
        {"outcome_id": "o1", "adr_ids": ["ADR-3"], "reason": "и ещё"},   # тот же итог — одна
        {"outcome_id": "O7", "adr_ids": ["ADR-3"], "reason": "чужой итог"},
        {"outcome_id": "O1", "adr_ids": ["ADR-1"], "reason": "его же решение — не пометка"},
    ]}, context).touches
    assert touches == (Touch("O1", ("ADR-3",), "меняет поиск; и ещё"),)
