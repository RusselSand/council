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

CONTEXT = Context(adrs=frozenset({"ADR-1"}), constraints=frozenset({4}),
                  risks=frozenset({5}), open_questions=frozenset({"Q2"}))


def outcome(title="Поиск по базе знаний", behavior="Человек находит статью через поиск.",
            **extra):
    """Итог из ответа; строка «что следует» — на каждое реализуемое решение, если не задано."""
    data = {"title": title, "behavior": behavior, "adr_ids": ["ADR-1"],
            "constraint_ids": ["F4"], "risk_ids": [],
            "acceptance_criteria": ["Запрос возвращает подходящие статьи."],
            "blocked_by": [], "gaps": [], **extra}
    data.setdefault("adr_notes", {adr: f"Из {adr} следует поиск." for adr in data["adr_ids"]})
    return data


def test_an_outcome_is_read_with_its_links():
    [found] = outcome_list({"outcomes": [outcome(
        adr_ids=["adr-3", "ADR 1", "ADR-2"], risk_ids=["F5", "F4"], blocked_by=["q2", "Q1"],
        acceptance_criteria=["  Запрос  возвращает статьи. ", "", "Запрос возвращает статьи."],
        gaps=[{"question": "Кто обновляет индекс?", "reason": "без этого нет критерия"},
              {"question": " "}, "пробел"])]}, replace(CONTEXT, adrs=frozenset({"ADR-1", "ADR-3"})))
    assert found == Candidate(
        "Поиск по базе знаний", "Человек находит статью через поиск.", ("ADR-1", "ADR-3"),
        (4,), (5,), ("Запрос возвращает статьи.",), ("Q2",),
        (Gap("Кто обновляет индекс?", "без этого нет критерия"),),
        notes=(("ADR-1", "Из ADR 1 следует поиск."), ("ADR-3", "Из adr-3 следует поиск.")))


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
    assert outcome_list({"outcomes": [], "coverage": {}}, replace(CONTEXT, adrs=frozenset())) == []
    with pytest.raises(BadAnswer, match="outcomes"):
        outcome_list({"items": []}, CONTEXT)


def test_the_judge_sees_an_outcome_as_the_participants_were_asked_for_it():
    [found] = outcome_list({"outcomes": [outcome(blocked_by=["Q2"])]}, CONTEXT)
    assert as_prompt(found) == {
        "title": "Поиск по базе знаний", "behavior": "Человек находит статью через поиск.",
        "adr_ids": ["ADR-1"], "adr_notes": {"ADR-1": "Из ADR-1 следует поиск."},
        "relies_on_adr_ids": [], "project_decision_ids": [], "constraint_ids": ["F4"],
        "risk_ids": [], "acceptance_criteria": ["Запрос возвращает подходящие статьи."],
        "blocked_by": ["Q2"], "gaps": []}


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
    context = replace(CONTEXT, adrs=frozenset({"ADR-1", "ADR-3"}),
                      kept={"O1": frozenset({"ADR-1"})})
    touches = assembly_of({"outcomes": [], "touches": [
        {"outcome_id": "O1", "adr_ids": ["ADR-1", "ADR-3"], "reason": "меняет поиск"},
        {"outcome_id": "o1", "adr_ids": ["ADR-3"], "reason": "и ещё"},   # тот же итог — одна
        {"outcome_id": "O7", "adr_ids": ["ADR-3"], "reason": "чужой итог"},
        {"outcome_id": "O1", "adr_ids": ["ADR-1"], "reason": "его же решение — не пометка"},
    ]}, context).touches
    assert touches == (Touch("O1", ("ADR-3",), "меняет поиск; и ещё"),)


def test_every_decision_is_in_exactly_one_outcome():
    """Решения раскладываются по итогам: без итога или в двух — негодный ответ."""
    context = replace(CONTEXT, adrs=frozenset({"ADR-1", "ADR-3"}))
    with pytest.raises(BadAnswer, match="решения не реализует ни один итог: ADR-3"):
        assembly_of({"outcomes": [outcome()]}, context)
    with pytest.raises(BadAnswer, match="решения реализуют два итога: ADR-1"):
        assembly_of({"outcomes": [outcome(adr_ids=["ADR-1", "ADR-3"]),
                                  outcome("Отчёт", adr_ids=["ADR-1"])]}, context)
    found = assembly_of({"outcomes": [outcome(), outcome("Отчёт", adr_ids=["ADR-3"])]}, context)
    assert [o.adr_ids for o in found.outcomes] == [("ADR-1",), ("ADR-3",)]


def test_a_decision_of_a_kept_outcome_is_its_own_and_a_touch_covers_a_new_one():
    context = replace(CONTEXT, adrs=frozenset({"ADR-1", "ADR-3"}),
                      kept={"O1": frozenset({"ADR-1"})})
    with pytest.raises(BadAnswer, match="реализуют два итога: ADR-1"):
        assembly_of({"outcomes": [outcome(adr_ids=["ADR-1", "ADR-3"])]}, context)
    assert assembly_of({"outcomes": [outcome(adr_ids=["ADR-3"])]}, context).outcomes
    touched = assembly_of({"outcomes": [], "touches": [
        {"outcome_id": "O1", "adr_ids": ["ADR-3"], "reason": "меняет поиск"}]}, context)
    assert touched.touches == (Touch("O1", ("ADR-3",), "меняет поиск"),)


def test_an_outcome_names_only_project_decisions_chosen_for_the_stream():
    context = replace(CONTEXT, project_decisions=frozenset({"ADR-0007", "ADR-0012"}))
    [found] = outcome_list({"outcomes": [outcome(
        project_decision_ids=["ADR-7", "adr-0012", "ADR-0099", "ADR-1"])]}, context)
    assert (found.adr_ids, found.project_decision_ids) == (("ADR-1",), ("ADR-0007", "ADR-0012"))


def test_an_outcome_relies_on_decisions_another_one_implements():
    """Решение реализует один итог, опираться на него могут многие: так итог его не теряет."""
    context = replace(CONTEXT, adrs=frozenset({"ADR-1", "ADR-3"}))
    found = assembly_of({"outcomes": [
        outcome(relies_on_adr_ids=["ADR-3", "ADR-1", "ADR-9"]),
        outcome("Отчёт", adr_ids=["ADR-3"], relies_on_adr_ids=["ADR-1"]),
        outcome("Плашка", adr_ids=[], relies_on_adr_ids=["ADR-1", "ADR-3"])]}, context)
    assert [(o.adr_ids, o.relies_on) for o in found.outcomes] == [
        (("ADR-1",), ("ADR-3",)), (("ADR-3",), ("ADR-1",)), ((), ("ADR-1", "ADR-3"))]


def test_an_implemented_decision_needs_a_line_on_what_follows_from_it():
    """Без строки «что следует из решения» итог негодный; строки к чужим решениям — мимо."""
    context = replace(CONTEXT, adrs=frozenset({"ADR-1", "ADR-3"}))
    with pytest.raises(BadAnswer, match="не сказано, что следует из ADR-3"):
        outcome_list({"outcomes": [outcome(adr_ids=["ADR-1", "ADR-3"],
                                           adr_notes={"ADR-1": "Поиск по слову.", "ADR-3": " "})]},
                     context)
    [found] = outcome_list({"outcomes": [outcome(adr_ids=["ADR-1", "ADR-3"], adr_notes={
        "adr-1": "Поиск по слову.", "ADR-3": "Индекс ночью.", "ADR-9": "чужое"})]}, context)
    assert found.notes == (("ADR-1", "Поиск по слову."), ("ADR-3", "Индекс ночью."))
